from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.credit_tracker import CreditTracker
from app.db import get_db
from app.hunter_client import HunterClient
from app.models import Company, Contact, DiscoveryUsage
from app.routes.intake import get_or_create_default_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Hunter's free plan caps domain-search results at 10 per request.
RESULTS_PER_SEARCH = 10
COST_PER_SEARCH = 1
PERIOD_LENGTH_DAYS = 30


def _load_usage(db: Session) -> DiscoveryUsage:
    usage = db.query(DiscoveryUsage).first()
    if usage is None:
        usage = DiscoveryUsage(used=0, period_start=date.today())
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


@router.get("/contacts")
def list_contacts(request: Request, db: Session = Depends(get_db)):
    contacts = db.query(Contact).all()
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.hunter_monthly_search_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    # Roll the period over here too, so the displayed search count matches what
    # POST /contacts/discover would enforce instead of showing a stale count.
    tracker.reset_if_new_period(today=date.today())
    if tracker.used != usage.used or tracker.period_start != usage.period_start:
        usage.used = tracker.used
        usage.period_start = tracker.period_start
        db.commit()

    return templates.TemplateResponse(
        "contacts.html",
        {
            "request": request,
            "contacts": contacts,
            "searches_remaining": tracker.remaining(),
            "searches_limit": tracker.limit,
        },
    )


@router.post("/contacts/discover")
def discover_contacts(domain: str = Form(...), db: Session = Depends(get_db)):
    domain = domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Please enter a company domain, e.g. example.com.")

    user = get_or_create_default_user(db)
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.hunter_monthly_search_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    tracker.reset_if_new_period(today=date.today())

    if not tracker.can_spend(COST_PER_SEARCH):
        resets_on = tracker.period_start + timedelta(days=PERIOD_LENGTH_DAYS)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Out of Hunter.io searches until period resets. "
                f"{tracker.remaining()} remaining. Resets on {resets_on}."
            ),
        )

    hunter_client = HunterClient(api_key=settings.hunter_api_key)
    people = hunter_client.domain_search(domain, limit=RESULTS_PER_SEARCH)

    for person in people:
        company = None
        if person.company_domain:
            company = db.query(Company).filter_by(domain=person.company_domain).first()
        if company is None:
            company = Company(
                name=person.company_name or domain,
                domain=person.company_domain,
                source="hunter",
            )
            db.add(company)
            db.commit()
            db.refresh(company)

        # Dedupe on linkedin_url when present, else on email — Hunter doesn't
        # always return a LinkedIn URL for a given person.
        existing = None
        if person.linkedin_url:
            existing = (
                db.query(Contact)
                .filter_by(linkedin_url=person.linkedin_url, user_id=user.id)
                .first()
            )
        elif person.email:
            existing = (
                db.query(Contact).filter_by(email=person.email, user_id=user.id).first()
            )
        if existing is None:
            db.add(
                Contact(
                    user_id=user.id,
                    company_id=company.id,
                    name=person.name,
                    title=person.title,
                    linkedin_url=person.linkedin_url,
                    email=person.email,
                    discovery_source="hunter",
                )
            )

    tracker.spend(COST_PER_SEARCH)
    usage.used = tracker.used
    usage.period_start = tracker.period_start
    db.commit()

    # Browser form post: send the user back to the contacts page rather than
    # rendering raw JSON.
    return RedirectResponse(url="/contacts", status_code=303)
