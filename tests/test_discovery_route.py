import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.apollo_client import ApolloPerson
from app.models import Profile, User


def _create_profile(db, target_roles=None, target_locations=None):
    user = User(email="local-user@contactcreator.local")
    db.add(user)
    db.commit()
    db.refresh(user)

    profile = Profile(
        user_id=user.id,
        cv_text="cv text",
        skills=json.dumps(["Java"]),
        years_experience=5,
        domains=json.dumps(["banking"]),
        target_roles=json.dumps(["Backend Engineer"] if target_roles is None else target_roles),
        target_locations=json.dumps(["Yerevan"] if target_locations is None else target_locations),
        seniority="mid",
        tone="professional",
    )
    db.add(profile)
    db.commit()
    return user


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_creates_company_and_contact(mock_apollo_cls, client):
    from app.db import SessionLocal

    db = SessionLocal()
    _create_profile(db)
    db.close()

    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = [
        ApolloPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_apollo_cls.return_value = mock_apollo

    response = client.post("/contacts/discover", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/contacts"

    from app.models import Contact

    db = SessionLocal()
    contacts = db.query(Contact).all()
    assert len(contacts) == 1
    assert contacts[0].name == "Jane Doe"
    db.close()

    list_response = client.get("/contacts")
    assert "Jane Doe" in list_response.text
    assert "Example Bank" in list_response.text


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_dedupes_company_and_contact_on_repeat(mock_apollo_cls, client):
    from app.db import SessionLocal
    from app.models import Company, Contact

    db = SessionLocal()
    _create_profile(db)
    db.close()

    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = [
        ApolloPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_apollo_cls.return_value = mock_apollo

    first_response = client.post("/contacts/discover", follow_redirects=False)
    assert first_response.status_code == 303
    assert first_response.headers["location"] == "/contacts"

    second_response = client.post("/contacts/discover", follow_redirects=False)
    assert second_response.status_code == 303

    db = SessionLocal()
    assert db.query(Company).count() == 1
    assert db.query(Contact).count() == 1
    db.close()


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_dedupes_on_linkedin_url_not_email(mock_apollo_cls, client):
    """Apollo's free tier reuses one locked placeholder email across people.

    Distinct linkedin_urls must produce distinct Contacts even when the email
    is identical, and a repeat search must not re-insert people whose email is
    missing entirely.
    """
    from app.db import SessionLocal
    from app.models import Contact

    db = SessionLocal()
    _create_profile(db)
    db.close()

    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = [
        ApolloPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="email_not_unlocked@domain.com",
        ),
        ApolloPerson(
            name="John Smith",
            title="Director of Engineering",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/johnsmith",
            email="email_not_unlocked@domain.com",
        ),
        ApolloPerson(
            name="No Email Person",
            title="Recruiter",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/noemailperson",
            email=None,
        ),
    ]
    mock_apollo_cls.return_value = mock_apollo

    assert client.post("/contacts/discover", follow_redirects=False).status_code == 303

    db = SessionLocal()
    names = sorted(c.name for c in db.query(Contact).all())
    db.close()
    # Same placeholder email, different people -> three distinct contacts.
    assert names == ["Jane Doe", "John Smith", "No Email Person"]

    # A repeat search dedupes all three, including the one with no email.
    assert client.post("/contacts/discover", follow_redirects=False).status_code == 303

    db = SessionLocal()
    assert db.query(Contact).count() == 3
    db.close()


def test_discover_contacts_requires_profile(client):
    response = client.post("/contacts/discover", follow_redirects=False)
    assert response.status_code == 400


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_blocks_when_out_of_credits(mock_apollo_cls, client):
    from app.db import SessionLocal
    from app.models import ApolloUsage

    period_start = date.today()
    db = SessionLocal()
    _create_profile(db)
    db.add(ApolloUsage(used=60, period_start=period_start))
    db.commit()
    db.close()

    response = client.post("/contacts/discover", follow_redirects=False)

    assert response.status_code == 429
    detail = response.json()["detail"]
    # The user is told when credits come back.
    assert str(period_start + timedelta(days=30)) in detail
    mock_apollo_cls.assert_not_called()


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_rejects_empty_search_criteria(mock_apollo_cls, client):
    """No target roles -> 400 and no credits spent, no Apollo call."""
    from app.db import SessionLocal
    from app.models import ApolloUsage

    db = SessionLocal()
    _create_profile(db, target_roles=[])
    db.close()

    response = client.post("/contacts/discover", follow_redirects=False)

    assert response.status_code == 400
    assert "target roles or locations" in response.json()["detail"]
    mock_apollo_cls.assert_not_called()

    db = SessionLocal()
    usage = db.query(ApolloUsage).first()
    assert usage.used == 0
    db.close()


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_rejects_empty_locations(mock_apollo_cls, client):
    from app.db import SessionLocal

    db = SessionLocal()
    _create_profile(db, target_locations=[])
    db.close()

    response = client.post("/contacts/discover", follow_redirects=False)

    assert response.status_code == 400
    mock_apollo_cls.assert_not_called()


def test_list_contacts_shows_reset_credits_after_period_rollover(client):
    """GET /contacts must roll the period over itself, not wait for a POST."""
    from app.db import SessionLocal
    from app.config import settings
    from app.models import ApolloUsage

    db = SessionLocal()
    _create_profile(db)
    # A fully-spent period that ended 31 days ago.
    db.add(ApolloUsage(used=60, period_start=date.today() - timedelta(days=31)))
    db.commit()
    db.close()

    response = client.get("/contacts")

    assert response.status_code == 200
    limit = settings.apollo_monthly_credit_limit
    assert f"{limit} / {limit}" in response.text

    # The rollover is persisted, not just displayed.
    db = SessionLocal()
    usage = db.query(ApolloUsage).first()
    assert usage.used == 0
    assert usage.period_start == date.today()
    db.close()


def test_list_contacts_shows_used_credits_within_period(client):
    """Guard against the rollover resetting a period that is still current."""
    from app.db import SessionLocal
    from app.config import settings
    from app.models import ApolloUsage

    db = SessionLocal()
    _create_profile(db)
    db.add(ApolloUsage(used=25, period_start=date.today() - timedelta(days=3)))
    db.commit()
    db.close()

    response = client.get("/contacts")

    limit = settings.apollo_monthly_credit_limit
    assert f"{limit - 25} / {limit}" in response.text

    db = SessionLocal()
    usage = db.query(ApolloUsage).first()
    assert usage.used == 25
    db.close()
