import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
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

    if not tracker.can_spend(RESULTS_PER_SEARCH):
        raise HTTPException(
            status_code=429,
            detail=f"Out of Apollo credits until period resets. {tracker.remaining()} remaining.",
        )

    criteria = SearchCriteria(
        titles=json.loads(profile.target_roles),
        locations=json.loads(profile.target_locations),
        industries=json.loads(profile.domains),
        per_page=RESULTS_PER_SEARCH,
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

        existing = None
        if person.email:
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
                    discovery_source="apollo",
                )
            )

    tracker.spend(RESULTS_PER_SEARCH)
    usage.used = tracker.used
    usage.period_start = tracker.period_start
    db.commit()

    return {"discovered": len(people), "credits_remaining": tracker.remaining()}
