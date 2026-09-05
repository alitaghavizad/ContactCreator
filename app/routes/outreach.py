import json
from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.business_days import business_days_from
from app.config import settings
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_linkedin_note
from app.models import Contact, Event, OutreachChannel, OutreachMessage, OutreachStatus, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _profile_summary(profile) -> str:
    skills = ", ".join(json.loads(profile.skills or "[]"))
    domains = ", ".join(json.loads(profile.domains or "[]"))
    return (
        f"{profile.years_experience} years of experience. "
        f"Skills: {skills}. Domain expertise: {domains}. Seniority: {profile.seniority}."
    )


def _log_event(db: Session, contact_id: int, event_type: str, note: str) -> None:
    db.add(Event(contact_id=contact_id, type=event_type, note=note, timestamp=datetime.utcnow()))


@router.post("/outreach/generate/{contact_id}")
def generate_drafts(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter_by(id=contact_id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    user = db.query(User).filter_by(id=contact.user_id).first()
    if user is None or user.profile is None:
        raise HTTPException(status_code=400, detail="Complete intake first at /intake.")

    summary = _profile_summary(user.profile)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    company_name = contact.company.name if contact.company else "their company"

    try:
        linkedin_text = draft_linkedin_note(
            profile_summary=summary,
            contact_name=contact.name,
            contact_title=contact.title or "",
            company_name=company_name,
            client=client,
            model=settings.claude_model,
        )
        email_text = draft_email(
            profile_summary=summary,
            contact_name=contact.name,
            contact_title=contact.title or "",
            company_name=company_name,
            client=client,
            model=settings.claude_model,
        )
    except DraftingError:
        raise HTTPException(
            status_code=502, detail="Could not generate outreach drafts. Please try again."
        )

    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.linkedin,
            draft_text=linkedin_text,
            status=OutreachStatus.drafted,
        )
    )
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.email,
            draft_text=email_text,
            status=OutreachStatus.drafted,
        )
    )
    db.commit()

    # Browser form post: send the user to the review queue rather than raw JSON.
    return RedirectResponse(url="/outreach", status_code=303)


@router.get("/outreach")
def list_outreach(request: Request, db: Session = Depends(get_db)):
    messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.drafted).all()
    )
    return templates.TemplateResponse("outreach.html", {"request": request, "messages": messages})


@router.post("/outreach/{message_id}/mark-sent")
def mark_sent(message_id: int, db: Session = Depends(get_db)):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    old_status = message.status
    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    follow_up_date = business_days_from(
        message.sent_at.date(), settings.follow_up_business_days
    )
    message.follow_up_due_at = datetime.combine(follow_up_date, message.sent_at.time())
    _log_event(
        db, message.contact_id, OutreachStatus.sent.value, f"{old_status.value} -> sent"
    )
    db.commit()

    # Browser form post: send the user back to the review queue.
    return RedirectResponse(url="/outreach", status_code=303)
