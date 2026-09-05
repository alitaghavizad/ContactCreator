import json
from datetime import datetime, timedelta

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_linkedin_note
from app.models import Contact, OutreachChannel, OutreachMessage, OutreachStatus, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _profile_summary(profile) -> str:
    skills = ", ".join(json.loads(profile.skills or "[]"))
    domains = ", ".join(json.loads(profile.domains or "[]"))
    return (
        f"{profile.years_experience} years of experience. "
        f"Skills: {skills}. Domain expertise: {domains}. Seniority: {profile.seniority}."
    )


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

    return {"linkedin": linkedin_text, "email": email_text}


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

    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    message.follow_up_due_at = datetime.utcnow() + timedelta(days=6)
    db.commit()

    return {"status": "sent", "follow_up_due_at": message.follow_up_due_at.isoformat()}
