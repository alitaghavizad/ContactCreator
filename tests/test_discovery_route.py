from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.hunter_client import HunterAPIError, HunterPerson


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_creates_company_and_contact(mock_hunter_cls, client):
    from app.db import SessionLocal

    mock_hunter = MagicMock()
    mock_hunter.domain_search.return_value = [
        HunterPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_hunter_cls.return_value = mock_hunter

    response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/contacts"
    mock_hunter.domain_search.assert_called_once_with("example.com", limit=10)

    from app.models import Contact

    db = SessionLocal()
    contacts = db.query(Contact).all()
    assert len(contacts) == 1
    assert contacts[0].name == "Jane Doe"
    db.close()

    list_response = client.get("/contacts")
    assert "Jane Doe" in list_response.text
    assert "Example Bank" in list_response.text


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_lowercases_and_strips_domain(mock_hunter_cls, client):
    mock_hunter = MagicMock()
    mock_hunter.domain_search.return_value = []
    mock_hunter_cls.return_value = mock_hunter

    response = client.post(
        "/contacts/discover", data={"domain": "  Example.COM  "}, follow_redirects=False
    )

    assert response.status_code == 303
    mock_hunter.domain_search.assert_called_once_with("example.com", limit=10)


def test_discover_contacts_rejects_empty_domain(client):
    response = client.post("/contacts/discover", data={"domain": "   "}, follow_redirects=False)
    assert response.status_code == 400
    assert "domain" in response.json()["detail"].lower()


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_dedupes_company_and_contact_on_repeat(mock_hunter_cls, client):
    from app.db import SessionLocal
    from app.models import Company, Contact

    mock_hunter = MagicMock()
    mock_hunter.domain_search.return_value = [
        HunterPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_hunter_cls.return_value = mock_hunter

    first_response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )
    assert first_response.status_code == 303

    second_response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )
    assert second_response.status_code == 303

    db = SessionLocal()
    assert db.query(Company).count() == 1
    assert db.query(Contact).count() == 1
    db.close()


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_dedupes_on_linkedin_url_or_email(mock_hunter_cls, client):
    """Distinct linkedin_urls produce distinct Contacts; a person with no
    linkedin_url falls back to deduping on email instead."""
    from app.db import SessionLocal
    from app.models import Contact

    mock_hunter = MagicMock()
    mock_hunter.domain_search.return_value = [
        HunterPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        ),
        HunterPerson(
            name="No LinkedIn Person",
            title="Recruiter",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url=None,
            email="nolinkedin@example.com",
        ),
    ]
    mock_hunter_cls.return_value = mock_hunter

    assert (
        client.post(
            "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
        ).status_code
        == 303
    )

    db = SessionLocal()
    names = sorted(c.name for c in db.query(Contact).all())
    db.close()
    assert names == ["Jane Doe", "No LinkedIn Person"]

    # A repeat search dedupes both, including the one with no LinkedIn URL.
    assert (
        client.post(
            "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
        ).status_code
        == 303
    )

    db = SessionLocal()
    assert db.query(Contact).count() == 2
    db.close()


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_blocks_when_out_of_searches(mock_hunter_cls, client):
    from app.db import SessionLocal
    from app.models import DiscoveryUsage

    period_start = date.today()
    db = SessionLocal()
    db.add(DiscoveryUsage(used=25, period_start=period_start))
    db.commit()
    db.close()

    response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )

    assert response.status_code == 429
    detail = response.json()["detail"]
    # The user is told when searches come back.
    assert str(period_start + timedelta(days=30)) in detail
    mock_hunter_cls.assert_not_called()


def test_list_contacts_shows_reset_searches_after_period_rollover(client):
    """GET /contacts must roll the period over itself, not wait for a POST."""
    from app.db import SessionLocal
    from app.config import settings
    from app.models import DiscoveryUsage

    db = SessionLocal()
    # A fully-spent period that ended 31 days ago.
    db.add(DiscoveryUsage(used=25, period_start=date.today() - timedelta(days=31)))
    db.commit()
    db.close()

    response = client.get("/contacts")

    assert response.status_code == 200
    limit = settings.hunter_monthly_search_limit
    assert f"{limit} / {limit}" in response.text

    # The rollover is persisted, not just displayed.
    db = SessionLocal()
    usage = db.query(DiscoveryUsage).first()
    assert usage.used == 0
    assert usage.period_start == date.today()
    db.close()


def test_list_contacts_shows_used_searches_within_period(client):
    """Guard against the rollover resetting a period that is still current."""
    from app.db import SessionLocal
    from app.config import settings
    from app.models import DiscoveryUsage

    db = SessionLocal()
    db.add(DiscoveryUsage(used=10, period_start=date.today() - timedelta(days=3)))
    db.commit()
    db.close()

    response = client.get("/contacts")

    limit = settings.hunter_monthly_search_limit
    assert f"{limit - 10} / {limit}" in response.text

    db = SessionLocal()
    usage = db.query(DiscoveryUsage).first()
    assert usage.used == 10
    db.close()


@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_returns_502_on_hunter_api_error(mock_hunter_cls, client):
    from app.db import SessionLocal
    from app.models import Company, Contact

    mock_hunter = MagicMock()
    mock_hunter.domain_search.side_effect = HunterAPIError("Hunter.io returned an error: 401")
    mock_hunter_cls.return_value = mock_hunter

    response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )

    assert response.status_code == 502
    assert "Hunter.io" in response.json()["detail"]

    db = SessionLocal()
    assert db.query(Company).count() == 0
    assert db.query(Contact).count() == 0
    db.close()
