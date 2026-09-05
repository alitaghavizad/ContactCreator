import json
from datetime import date
from unittest.mock import MagicMock, patch

from app.apollo_client import ApolloPerson
from app.models import Profile, User


def _create_profile(db):
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
        target_roles=json.dumps(["Backend Engineer"]),
        target_locations=json.dumps(["Yerevan"]),
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

    response = client.post("/contacts/discover")

    assert response.status_code == 200
    body = response.json()
    assert body["discovered"] == 1

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

    first_response = client.post("/contacts/discover")
    assert first_response.status_code == 200
    assert first_response.json()["discovered"] == 1

    second_response = client.post("/contacts/discover")
    assert second_response.status_code == 200
    assert second_response.json()["discovered"] == 1

    db = SessionLocal()
    assert db.query(Company).count() == 1
    assert db.query(Contact).count() == 1
    db.close()


def test_discover_contacts_requires_profile(client):
    response = client.post("/contacts/discover")
    assert response.status_code == 400


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_blocks_when_out_of_credits(mock_apollo_cls, client):
    from app.db import SessionLocal
    from app.models import ApolloUsage

    db = SessionLocal()
    _create_profile(db)
    db.add(ApolloUsage(used=60, period_start=date.today()))
    db.commit()
    db.close()

    response = client.post("/contacts/discover")

    assert response.status_code == 429
    mock_apollo_cls.assert_not_called()
