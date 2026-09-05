import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.apollo_client import ApolloClient, SearchCriteria
from app.config import settings
from app.credit_tracker import CreditTracker
from app.db import get_db
from app.models import ApolloUsage, Company, Contact, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

RESULTS_PER_SEARCH = 25
PERIOD_LENGTH_DAYS = 30


def _load_usage(db: Session) -> ApolloUsage:
    usage = db.query(ApolloUsage).first()
    if usage is None:
        usage = ApolloUsage(used=0, period_start=date.today())
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


@router.get("/contacts")
def list_contacts(request: Request, db: Session = Depends(get_db)):
    contacts = db.query(Contact).all()
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.apollo_monthly_credit_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    # Roll the period over here too, so the displayed credit count matches what
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
            "credits_remaining": tracker.remaining(),
            "credits_limit": tracker.limit,
        },
    )


@router.post("/contacts/discover")
def discover_contacts(db: Session = Depends(get_db)):
    user = db.query(User).first()
    if user is None or user.profile is None:
        raise HTTPException(status_code=400, detail="Complete intake first at /intake.")

    profile = user.profile
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.apollo_monthly_credit_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    tracker.reset_if_new_period(today=date.today())

    criteria = SearchCriteria(
        titles=json.loads(profile.target_roles or "[]"),
        locations=json.loads(profile.target_locations or "[]"),
        industries=json.loads(profile.domains or "[]"),
        per_page=RESULTS_PER_SEARCH,
    )
    # Never spend credits on an unfiltered search.
    if not criteria.titles or not criteria.locations:
        raise HTTPException(
            status_code=400,
            detail=(
                "Your profile has no target roles or locations — please update "
                "your intake answers before discovering contacts."
            ),
        )

    if not tracker.can_spend(RESULTS_PER_SEARCH):
        resets_on = tracker.period_start + timedelta(days=PERIOD_LENGTH_DAYS)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Out of Apollo credits until period resets. "
                f"{tracker.remaining()} remaining. Resets on {resets_on}."
            ),
        )

    apollo_client = ApolloClient(api_key=settings.apollo_api_key)
    people = apollo_client.search_people(criteria)

    for person in people:
        company = None
        if person.company_domain:
            company = db.query(Company).filter_by(domain=person.company_domain).first()
        if company is None:
            company = Company(
                name=person.company_name or "Unknown",
                domain=person.company_domain,
                source="apollo",
            )
            db.add(company)
            db.commit()
            db.refresh(company)

        # Dedupe on linkedin_url, not email: Apollo's free tier returns the same
        # locked placeholder email (email_not_unlocked@domain.com) for many
        # different people, and returns no email at all for others.
        existing = None
        if person.linkedin_url:
            existing = (
                db.query(Contact)
                .filter_by(linkedin_url=person.linkedin_url, user_id=user.id)
                .first()
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
                    discovery_source="apollo",
                )
            )

    tracker.spend(RESULTS_PER_SEARCH)
    usage.used = tracker.used
    usage.period_start = tracker.period_start
    db.commit()

    # Browser form post: send the user back to the contacts page rather than
    # rendering raw JSON.
    return RedirectResponse(url="/contacts", status_code=303)
