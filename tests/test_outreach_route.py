import json
from unittest.mock import MagicMock, patch

from app.drafting import DraftingError
from app.models import Company, Contact, OutreachMessage, Profile, User


def _create_contact(db):
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

    company = Company(name="Example Bank", domain="example.com", source="apollo")
    db.add(company)
    db.commit()
    db.refresh(company)

    contact = Contact(
        user_id=user.id,
        company_id=company.id,
        name="Jane Doe",
        title="Engineering Manager",
        linkedin_url="https://linkedin.com/in/janedoe",
        email="jane@example.com",
        discovery_source="apollo",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _mock_anthropic_returning(text: str):
    mock_client = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = text
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    return mock_client


@patch("app.routes.outreach.anthropic.Anthropic")
def test_generate_drafts_creates_two_messages(mock_anthropic_cls, client):
    from app.db import SessionLocal

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()

    mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")

    response = client.post(f"/outreach/generate/{contact_id}")

    assert response.status_code == 200
    body = response.json()
    assert "linkedin" in body
    assert "email" in body

    outreach_response = client.get("/outreach")
    assert "Jane Doe" in outreach_response.text


@patch("app.routes.outreach.draft_linkedin_note", side_effect=DraftingError("empty response"))
@patch("app.routes.outreach.anthropic.Anthropic")
def test_generate_drafts_502_on_drafting_error(mock_anthropic_cls, mock_draft_linkedin, client):
    from app.db import SessionLocal

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()

    mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")

    response = client.post(f"/outreach/generate/{contact_id}")

    assert response.status_code == 502

    db = SessionLocal()
    messages = db.query(OutreachMessage).filter_by(contact_id=contact_id).all()
    db.close()
    assert messages == []


def test_generate_drafts_404_for_unknown_contact(client):
    response = client.post("/outreach/generate/9999")
    assert response.status_code == 404


@patch("app.routes.outreach.anthropic.Anthropic")
def test_mark_sent_updates_status_and_follow_up(mock_anthropic_cls, client):
    from app.db import SessionLocal
    from app.models import OutreachMessage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()

    mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")
    client.post(f"/outreach/generate/{contact_id}")

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(contact_id=contact_id).first()
    message_id = message.id
    db.close()

    response = client.post(f"/outreach/{message_id}/mark-sent")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert "follow_up_due_at" in body
