import json
from unittest.mock import MagicMock, patch

from app.drafting import DraftingError
from app.db import SessionLocal
from app.models import Company, Contact, OutreachMessage, OutreachStatus, Profile, User


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
    mock_content_block.type = "text"
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

    response = client.post(f"/outreach/generate/{contact_id}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/outreach"

    db = SessionLocal()
    messages = db.query(OutreachMessage).filter_by(contact_id=contact_id).all()
    channels = sorted(m.channel.value for m in messages)
    db.close()
    assert channels == ["email", "linkedin"]

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
    from app.business_days import business_days_from
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Event, OutreachMessage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()

    mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")
    client.post(f"/outreach/generate/{contact_id}", follow_redirects=False)

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(contact_id=contact_id).first()
    message_id = message.id
    db.close()

    response = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/outreach"

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert message.status == OutreachStatus.sent
    assert message.sent_at is not None
    assert message.follow_up_due_at is not None
    expected_date = business_days_from(message.sent_at.date(), settings.follow_up_business_days)
    assert message.follow_up_due_at.date() == expected_date

    events = db.query(Event).filter_by(contact_id=contact_id).all()
    assert len(events) == 1
    assert events[0].type == "sent"
    assert events[0].note == "drafted -> sent"
    db.close()

    # The sent message drops out of the review queue.
    queue = client.get("/outreach")
    assert f"/outreach/{message_id}/mark-sent" not in queue.text


def _create_sent_message(db, contact_id):
    from datetime import datetime

    from app.models import OutreachChannel, OutreachMessage, OutreachStatus

    message = OutreachMessage(
        contact_id=contact_id,
        channel=OutreachChannel.linkedin,
        draft_text="Hi there",
        status=OutreachStatus.sent,
        sent_at=datetime.utcnow(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def test_update_status_sent_to_replied(client):
    from app.db import SessionLocal
    from app.models import Event, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message_id = message.id
    contact_id = contact.id
    db.close()

    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "replied"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/outreach"

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.replied

    events = db.query(Event).filter_by(contact_id=contact_id).all()
    assert len(events) == 1
    assert events[0].type == "replied"
    assert events[0].note == "sent -> replied"
    db.close()


def test_update_status_sent_to_no_response(client):
    from app.db import SessionLocal
    from app.models import OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message_id = message.id
    db.close()

    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "no_response"}, follow_redirects=False
    )

    assert response.status_code == 303

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.no_response
    db.close()


def test_update_status_replied_to_interview(client):
    from app.db import SessionLocal
    from app.models import OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message.status = OutreachStatus.replied
    db.commit()
    message_id = message.id
    db.close()

    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "interview"}, follow_redirects=False
    )

    assert response.status_code == 303

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.interview
    db.close()


def test_update_status_replied_to_rejected(client):
    from app.db import SessionLocal
    from app.models import OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message.status = OutreachStatus.replied
    db.commit()
    message_id = message.id
    db.close()

    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "rejected"}, follow_redirects=False
    )

    assert response.status_code == 303

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.rejected
    db.close()


def test_update_status_rejects_invalid_transition(client):
    from app.db import SessionLocal
    from app.models import Event, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message_id = message.id
    contact_id = contact.id
    db.close()

    # sent -> interview is not a valid direct transition.
    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "interview"}, follow_redirects=False
    )

    assert response.status_code == 400

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.sent
    assert db.query(Event).filter_by(contact_id=contact_id).count() == 0
    db.close()


def test_update_status_rejects_unknown_status_value(client):
    from app.db import SessionLocal

    db = SessionLocal()
    contact = _create_contact(db)
    message = _create_sent_message(db, contact.id)
    message_id = message.id
    db.close()

    response = client.post(
        f"/outreach/{message_id}/status", data={"status": "bogus"}, follow_redirects=False
    )

    assert response.status_code == 400


def test_update_status_404_for_unknown_message(client):
    response = client.post(
        "/outreach/9999/status", data={"status": "replied"}, follow_redirects=False
    )
    assert response.status_code == 404


def test_outreach_page_shows_funnel_counts(client):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.linkedin,
            draft_text="a",
            status=OutreachStatus.sent,
            sent_at=datetime.utcnow(),
            follow_up_due_at=datetime.utcnow() + timedelta(days=10),
        )
    )
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.email,
            draft_text="b",
            status=OutreachStatus.replied,
        )
    )
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.email,
            draft_text="c",
            status=OutreachStatus.interview,
        )
    )
    db.commit()
    db.close()

    response = client.get("/outreach")

    assert response.status_code == 200
    # Contacted counts every sent-or-later message: sent + replied + interview = 3.
    assert "Contacted: 3" in response.text
    # Replied counts replied + interview = 2.
    assert "Replied: 2" in response.text
    assert "Interview: 1" in response.text


def test_outreach_page_shows_follow_ups_due_only_when_overdue(client):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.linkedin,
            draft_text="overdue one",
            status=OutreachStatus.sent,
            sent_at=datetime.utcnow() - timedelta(days=20),
            follow_up_due_at=datetime.utcnow() - timedelta(days=1),
        )
    )
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.email,
            draft_text="not due yet",
            status=OutreachStatus.sent,
            sent_at=datetime.utcnow(),
            follow_up_due_at=datetime.utcnow() + timedelta(days=10),
        )
    )
    db.commit()
    db.close()

    response = client.get("/outreach")

    assert "overdue one" in response.text
    assert "not due yet" not in response.text


def test_outreach_page_shows_replied_awaiting_outcome(client):
    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    message = OutreachMessage(
        contact_id=contact.id,
        channel=OutreachChannel.linkedin,
        draft_text="a",
        status=OutreachStatus.replied,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    message_id = message.id
    db.close()

    response = client.get("/outreach")

    assert f"/outreach/{message_id}/status" in response.text
