from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Contact, Event, OutreachMessage, OutreachStatus, Profile

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def overview(request: Request, db: Session = Depends(get_db)):
    messages = db.query(OutreachMessage).all()
    counts = {status.value: 0 for status in OutreachStatus}
    for message in messages:
        counts[message.status.value] += 1
    contacted = sum(counts[key] for key in ("sent", "replied", "interview", "rejected", "no_response"))
    replied = sum(counts[key] for key in ("replied", "interview", "rejected"))
    due = [m for m in messages if m.status == OutreachStatus.sent and m.follow_up_due_at and m.follow_up_due_at <= datetime.utcnow()]
    activity = (
        db.query(Event, Contact).join(Contact, Event.contact_id == Contact.id)
        .order_by(Event.timestamp.desc(), Event.id.desc()).limit(5).all()
    )
    return templates.TemplateResponse("overview.html", {
        "request": request, "contact_count": db.query(Contact).count(),
        "counts": counts, "contacted": contacted, "replied": replied,
        "due": due, "activity": activity,
        "has_profile": db.query(Profile).first() is not None,
    })
