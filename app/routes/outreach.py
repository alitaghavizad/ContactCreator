import json
from datetime import date, datetime, timedelta

import anthropic
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.business_days import business_days_from
from app.config import settings
from app.credit_tracker import CreditTracker
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_email_subject, draft_linkedin_note
from app.email_client import EmailSendError, SMTPEmailClient
from app.models import (
    Contact,
    Event,
    EmailSendUsage,
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    User,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

VALID_STATUS_VALUES = {"replied", "no_response", "interview", "rejected"}

VALID_TRANSITIONS = {
    OutreachStatus.drafted: {OutreachStatus.sent},
    OutreachStatus.sent: {OutreachStatus.replied, OutreachStatus.no_response},
    OutreachStatus.replied: {OutreachStatus.interview, OutreachStatus.rejected},
}

EMAIL_DAILY_PERIOD_DAYS = 1


def _profile_summary(profile) -> str:
    skills = ", ".join(json.loads(profile.skills or "[]"))
    domains = ", ".join(json.loads(profile.domains or "[]"))
    return (
        f"{profile.years_experience} years of experience. "
        f"Skills: {skills}. Domain expertise: {domains}. Seniority: {profile.seniority}."
    )


def _log_event(db: Session, contact_id: int, event_type: str, note: str) -> None:
    db.add(Event(contact_id=contact_id, type=event_type, note=note, timestamp=datetime.utcnow()))


def _load_email_usage(db: Session) -> EmailSendUsage:
    usage = db.query(EmailSendUsage).first()
    if usage is None:
        usage = EmailSendUsage(used=0, period_start=date.today())
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


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
        email_subject = draft_email_subject(
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
            subject=email_subject,
            status=OutreachStatus.drafted,
        )
    )
    db.commit()

    # Browser form post: send the user to the review queue rather than raw JSON.
    return RedirectResponse(url="/outreach", status_code=303)


@router.get("/outreach")
def list_outreach(request: Request, db: Session = Depends(get_db)):
    drafted_messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.drafted).all()
    )
    follow_ups_due = (
        db.query(OutreachMessage)
        .filter(
            OutreachMessage.status == OutreachStatus.sent,
            OutreachMessage.follow_up_due_at <= datetime.utcnow(),
        )
        .all()
    )
    replied_awaiting_outcome = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.replied).all()
    )
    failed_messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.failed).all()
    )

    contacted_statuses = [
        OutreachStatus.sent,
        OutreachStatus.replied,
        OutreachStatus.interview,
        OutreachStatus.rejected,
        OutreachStatus.no_response,
    ]
    replied_statuses = [OutreachStatus.replied, OutreachStatus.interview, OutreachStatus.rejected]

    contacted_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status.in_(contacted_statuses)).count()
    )
    replied_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status.in_(replied_statuses)).count()
    )
    interview_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.interview).count()
    )

    email_usage = _load_email_usage(db)
    email_tracker = CreditTracker(
        limit=settings.daily_email_send_limit,
        used=email_usage.used,
        period_start=email_usage.period_start,
    )
    email_tracker.reset_if_new_period(today=date.today(), period_length_days=EMAIL_DAILY_PERIOD_DAYS)
    if email_tracker.used != email_usage.used or email_tracker.period_start != email_usage.period_start:
        email_usage.used = email_tracker.used
        email_usage.period_start = email_tracker.period_start
        db.commit()

    return templates.TemplateResponse(
        "outreach.html",
        {
            "request": request,
            "messages": drafted_messages,
            "follow_ups_due": follow_ups_due,
            "replied_awaiting_outcome": replied_awaiting_outcome,
            "failed_messages": failed_messages,
            "contacted_count": contacted_count,
            "replied_count": replied_count,
            "interview_count": interview_count,
            "emails_sent_today": email_tracker.used,
            "daily_email_limit": email_tracker.limit,
        },
    )


@router.post("/outreach/{message_id}/mark-sent")
def mark_sent(message_id: int, draft_text: str | None = Form(None), db: Session = Depends(get_db)):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.channel != OutreachChannel.linkedin:
        raise HTTPException(
            status_code=400,
            detail="Email messages must be sent via Send Email, not marked as sent manually.",
        )

    old_status = message.status
    if OutreachStatus.sent not in VALID_TRANSITIONS.get(old_status, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as sent from status {old_status.value}.",
        )

    if draft_text is not None:
        _apply_draft_edits(message, draft_text, None)
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


@router.post("/outreach/{message_id}/status")
def update_status(message_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    if status not in VALID_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail="Status must be one of: replied, no_response, interview, rejected.",
        )

    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    new_status = OutreachStatus(status)
    old_status = message.status
    allowed = VALID_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from {old_status.value} to {new_status.value}.",
        )

    message.status = new_status
    _log_event(
        db, message.contact_id, new_status.value, f"{old_status.value} -> {new_status.value}"
    )
    db.commit()

    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{message_id}/send-email")
def send_email(
    message_id: int,
    draft_text: str | None = Form(None),
    subject: str | None = Form(None),
    db: Session = Depends(get_db),
):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.channel != OutreachChannel.email:
        raise HTTPException(
            status_code=400, detail="This action is only available for email messages."
        )

    if message.status not in {OutreachStatus.drafted, OutreachStatus.failed}:
        raise HTTPException(
            status_code=400, detail=f"Cannot send from status {message.status.value}."
        )

    if not message.contact.email:
        raise HTTPException(status_code=400, detail="This contact has no email address on file.")

    usage = _load_email_usage(db)
    tracker = CreditTracker(
        limit=settings.daily_email_send_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    tracker.reset_if_new_period(today=date.today(), period_length_days=EMAIL_DAILY_PERIOD_DAYS)

    if not tracker.can_spend(1):
        resets_on = tracker.period_start + timedelta(days=EMAIL_DAILY_PERIOD_DAYS)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily email send limit reached. "
                f"{tracker.remaining()} remaining. Resets on {resets_on}."
            ),
        )

    if draft_text is not None:
        _apply_draft_edits(message, draft_text, subject)
    old_status = message.status
    email_client = SMTPEmailClient(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
    )

    try:
        email_client.send(message.contact.email, message.subject or "", message.draft_text)
    except EmailSendError as e:
        message.status = OutreachStatus.failed
        message.error_message = str(e)
        _log_event(
            db,
            message.contact_id,
            OutreachStatus.failed.value,
            f"{old_status.value} -> failed: {e}",
        )
        db.commit()
        return RedirectResponse(url="/outreach", status_code=303)

    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    follow_up_date = business_days_from(message.sent_at.date(), settings.follow_up_business_days)
    message.follow_up_due_at = datetime.combine(follow_up_date, message.sent_at.time())
    message.error_message = None
    _log_event(db, message.contact_id, OutreachStatus.sent.value, f"{old_status.value} -> sent")

    tracker.spend(1)
    usage.used = tracker.used
    usage.period_start = tracker.period_start

    db.commit()

    return RedirectResponse(url="/outreach", status_code=303)


def _apply_draft_edits(message: OutreachMessage, draft_text: str, subject: str | None):
    if not draft_text.strip():
        raise HTTPException(status_code=400, detail="Write a message before saving or sending.")
    if message.channel == OutreachChannel.linkedin and len(draft_text.strip()) > 300:
        raise HTTPException(status_code=400, detail="LinkedIn notes must be 300 characters or fewer.")
    if message.channel == OutreachChannel.email and subject is not None and ("\r" in subject or "\n" in subject):
        raise HTTPException(status_code=400, detail="Keep the subject on a single line.")
    message.draft_text = draft_text.strip()
    if message.channel == OutreachChannel.email and subject is not None:
        message.subject = subject.strip()


@router.post("/outreach/{message_id}/edit")
def edit_draft(
    message_id: int, draft_text: str = Form(...), subject: str | None = Form(None),
    db: Session = Depends(get_db),
):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.status not in {OutreachStatus.drafted, OutreachStatus.failed}:
        raise HTTPException(status_code=400, detail="Only unsent drafts can be edited.")
    _apply_draft_edits(message, draft_text, subject)
    db.commit()
    return RedirectResponse(url="/outreach?saved=1", status_code=303)
