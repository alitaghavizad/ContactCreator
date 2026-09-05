import json
from unittest.mock import MagicMock, patch

from app.drafting import DraftingError
from app.db import SessionLocal
from app.models import Company, Contact, OutreachMessage, OutreachStatus, Profile, User


def _create_contact(db, email="jane@example.com"):
    # Reuse the local user across multiple calls within the same test (e.g. a test that
    # needs two contacts) rather than violating User.email's unique constraint.
    user = db.query(User).filter_by(email="local-user@contactcreator.local").first()
    if user is None:
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
        email=email,
        discovery_source="apollo",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _section(html: str, heading: str) -> str:
    """Return the rendered outreach.html block under `<h2>{heading}</h2>`, up to the next <h2>."""
    marker = f"<h2>{heading}</h2>"
    assert marker in html, f"heading {heading!r} not found in page"
    body = html.split(marker, 1)[1]
    return body.split("<h2>", 1)[0]


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

    email_message = next(m for m in messages if m.channel.value == "email")
    linkedin_message = next(m for m in messages if m.channel.value == "linkedin")
    assert email_message.subject == "Hi Jane, ..."
    assert linkedin_message.subject is None

    outreach_response = client.get("/outreach")
    assert "Jane Doe" in outreach_response.text


@patch("app.routes.outreach.draft_email_subject", side_effect=DraftingError("empty response"))
@patch("app.routes.outreach.anthropic.Anthropic")
def test_generate_drafts_502_on_subject_drafting_error(
    mock_anthropic_cls, mock_draft_subject, client
):
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


@patch("app.routes.outreach.anthropic.Anthropic")
def test_mark_sent_rejects_already_sent_message(mock_anthropic_cls, client):
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

    first = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)
    assert first.status_code == 303

    db = SessionLocal()
    after_first = db.query(OutreachMessage).filter_by(id=message_id).first()
    sent_at = after_first.sent_at
    follow_up_due_at = after_first.follow_up_due_at
    db.close()

    # A double-click / back-button resubmit must not re-run the body.
    second = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)
    assert second.status_code == 400

    db = SessionLocal()
    after_second = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert after_second.status == OutreachStatus.sent
    assert after_second.sent_at == sent_at
    assert after_second.follow_up_due_at == follow_up_due_at

    events = db.query(Event).filter_by(contact_id=contact_id).all()
    assert len(events) == 1
    assert events[0].note == "drafted -> sent"
    db.close()


@patch("app.routes.outreach.anthropic.Anthropic")
def test_mark_sent_rejects_reverting_replied_message(mock_anthropic_cls, client):
    from app.db import SessionLocal
    from app.models import OutreachMessage

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

    assert client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False).status_code == 303
    assert (
        client.post(
            f"/outreach/{message_id}/status", data={"status": "replied"}, follow_redirects=False
        ).status_code
        == 303
    )

    # Re-marking a replied message as sent would wipe the reply state.
    response = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)
    assert response.status_code == 400

    db = SessionLocal()
    updated = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert updated.status == OutreachStatus.replied
    db.close()


@patch("app.routes.outreach.anthropic.Anthropic")
def test_full_outreach_lifecycle(mock_anthropic_cls, client):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()

    mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")
    generate = client.post(f"/outreach/generate/{contact_id}", follow_redirects=False)
    assert generate.status_code == 303

    db = SessionLocal()
    message = (
        db.query(OutreachMessage)
        .filter_by(contact_id=contact_id, channel=OutreachChannel.linkedin)
        .first()
    )
    message_id = message.id
    db.close()

    # Mark sent: real business-day follow-up window is computed by the route.
    marked = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)
    assert marked.status_code == 303

    db = SessionLocal()
    sent = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert sent.status == OutreachStatus.sent
    assert sent.follow_up_due_at is not None
    # Test setup: simulate the business-day window having elapsed.
    sent.follow_up_due_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    db.close()

    page = client.get("/outreach")
    assert page.status_code == 200

    # It now shows up under "Follow-ups due" (draft text + replied/no_response forms),
    # and no longer under "Drafts awaiting review".
    follow_ups = _section(page.text, "Follow-ups due")
    assert "Hi Jane, ..." in follow_ups
    assert f'action="/outreach/{message_id}/status"' in follow_ups
    assert 'value="replied"' in follow_ups
    assert "No follow-ups due right now." not in follow_ups
    assert f'action="/outreach/{message_id}/mark-sent"' not in page.text
    assert "Contacted: 1" in page.text
    assert "Replied: 0" in page.text

    replied = client.post(
        f"/outreach/{message_id}/status", data={"status": "replied"}, follow_redirects=False
    )
    assert replied.status_code == 303

    page = client.get("/outreach")
    # It moved out of "Follow-ups due" and into "Replied - awaiting outcome".
    follow_ups = _section(page.text, "Follow-ups due")
    assert f"/outreach/{message_id}/status" not in follow_ups
    assert "No follow-ups due right now." in follow_ups

    awaiting = _section(page.text, "Replied &mdash; awaiting outcome")
    assert f'action="/outreach/{message_id}/status"' in awaiting
    assert 'value="interview"' in awaiting
    assert "Jane Doe" in awaiting
    assert "Contacted: 1" in page.text
    assert "Replied: 1" in page.text


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


def _generate_drafts_for(client, contact_id):
    from unittest.mock import patch

    with patch("app.routes.outreach.anthropic.Anthropic") as mock_anthropic_cls:
        mock_anthropic_cls.return_value = _mock_anthropic_returning("Hi Jane, ...")
        client.post(f"/outreach/generate/{contact_id}", follow_redirects=False)


def _email_message_id(contact_id):
    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage

    db = SessionLocal()
    message = (
        db.query(OutreachMessage)
        .filter_by(contact_id=contact_id, channel=OutreachChannel.email)
        .first()
    )
    message_id = message.id
    db.close()
    return message_id


@patch("app.routes.outreach.SMTPEmailClient")
def test_send_email_success(mock_smtp_cls, client):
    from app.business_days import business_days_from
    from app.config import settings
    from app.db import SessionLocal
    from app.models import Event, EmailSendUsage, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    mock_smtp = MagicMock()
    mock_smtp_cls.return_value = mock_smtp

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/outreach"
    mock_smtp.send.assert_called_once_with("jane@example.com", "Hi Jane, ...", "Hi Jane, ...")

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert message.status == OutreachStatus.sent
    assert message.sent_at is not None
    assert message.error_message is None
    expected_date = business_days_from(message.sent_at.date(), settings.follow_up_business_days)
    assert message.follow_up_due_at.date() == expected_date

    events = db.query(Event).filter_by(contact_id=contact_id).all()
    assert len(events) == 1
    assert events[0].type == "sent"

    usage = db.query(EmailSendUsage).first()
    assert usage.used == 1
    db.close()


@patch("app.routes.outreach.SMTPEmailClient")
def test_send_email_failure_sets_failed_status_and_does_not_spend_cap(mock_smtp_cls, client):
    from app.email_client import EmailSendError
    from app.db import SessionLocal
    from app.models import Event, EmailSendUsage, OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    mock_smtp = MagicMock()
    mock_smtp.send.side_effect = EmailSendError("SMTP auth failed")
    mock_smtp_cls.return_value = mock_smtp

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    assert response.status_code == 303

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert message.status == OutreachStatus.failed
    assert message.error_message == "SMTP auth failed"

    events = db.query(Event).filter_by(contact_id=contact_id).all()
    assert len(events) == 1
    assert events[0].type == "failed"

    usage = db.query(EmailSendUsage).first()
    assert usage is None or usage.used == 0
    db.close()


@patch("app.routes.outreach.SMTPEmailClient")
def test_send_email_retry_after_failure_succeeds(mock_smtp_cls, client):
    from app.email_client import EmailSendError
    from app.db import SessionLocal
    from app.models import OutreachMessage, OutreachStatus

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    mock_smtp_fail = MagicMock()
    mock_smtp_fail.send.side_effect = EmailSendError("SMTP auth failed")
    mock_smtp_cls.return_value = mock_smtp_fail
    client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    mock_smtp_ok = MagicMock()
    mock_smtp_cls.return_value = mock_smtp_ok
    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    assert response.status_code == 303

    db = SessionLocal()
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    assert message.status == OutreachStatus.sent
    assert message.error_message is None
    db.close()


def test_send_email_rejects_linkedin_message(client):
    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)

    db = SessionLocal()
    linkedin_message = (
        db.query(OutreachMessage)
        .filter_by(contact_id=contact_id, channel=OutreachChannel.linkedin)
        .first()
    )
    message_id = linkedin_message.id
    db.close()

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)
    assert response.status_code == 400


def test_send_email_rejects_already_sent_message(client):
    from unittest.mock import MagicMock

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    with patch("app.routes.outreach.SMTPEmailClient") as mock_smtp_cls:
        mock_smtp_cls.return_value = MagicMock()
        client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)
    assert response.status_code == 400


def test_send_email_rejects_contact_with_no_email(client):
    db = SessionLocal()
    contact = _create_contact(db, email=None)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)
    assert response.status_code == 400


@patch("app.routes.outreach.SMTPEmailClient")
def test_send_email_blocked_when_daily_cap_exhausted(mock_smtp_cls, client):
    from datetime import date

    from app.config import settings
    from app.models import EmailSendUsage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.add(EmailSendUsage(used=settings.daily_email_send_limit, period_start=date.today()))
    db.commit()
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    response = client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    assert response.status_code == 429
    mock_smtp_cls.assert_not_called()


def test_outreach_page_shows_send_email_button_for_email_with_contact_email(client):
    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)

    response = client.get("/outreach")
    section = _section(response.text, "Drafts awaiting review")
    assert f'action="/outreach/{_email_message_id(contact_id)}/send-email"' in section


def test_outreach_page_shows_no_email_note_for_contact_without_email(client):
    db = SessionLocal()
    contact = _create_contact(db, email=None)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)

    response = client.get("/outreach")
    section = _section(response.text, "Drafts awaiting review")
    assert "No email on file" in section
    assert "/send-email" not in section


@patch("app.routes.outreach.SMTPEmailClient")
def test_outreach_page_shows_failed_sends_with_error_and_retry(mock_smtp_cls, client):
    from app.email_client import EmailSendError

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)
    message_id = _email_message_id(contact_id)

    mock_smtp = MagicMock()
    mock_smtp.send.side_effect = EmailSendError("SMTP auth failed")
    mock_smtp_cls.return_value = mock_smtp
    client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)

    response = client.get("/outreach")
    section = _section(response.text, "Failed sends")
    assert "SMTP auth failed" in section
    assert f'action="/outreach/{message_id}/send-email"' in section


def test_outreach_page_shows_daily_email_counter(client):
    from app.config import settings

    response = client.get("/outreach")
    assert f"Emails sent today: 0 / {settings.daily_email_send_limit}" in response.text


def test_full_email_lifecycle(client):
    from app.email_client import EmailSendError

    db = SessionLocal()
    ok_contact = _create_contact(db, email="jane@example.com")
    ok_contact_id = ok_contact.id
    fail_contact = _create_contact(db, email="john@example.com")
    fail_contact_id = fail_contact.id
    db.close()

    _generate_drafts_for(client, ok_contact_id)
    _generate_drafts_for(client, fail_contact_id)
    ok_message_id = _email_message_id(ok_contact_id)
    fail_message_id = _email_message_id(fail_contact_id)

    with patch("app.routes.outreach.SMTPEmailClient") as mock_smtp_cls:
        mock_smtp_cls.return_value = MagicMock()
        client.post(f"/outreach/{ok_message_id}/send-email", follow_redirects=False)

    page = client.get("/outreach")
    assert "Emails sent today: 1" in page.text
    assert "Contacted: 1" in page.text

    with patch("app.routes.outreach.SMTPEmailClient") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp.send.side_effect = EmailSendError("SMTP auth failed")
        mock_smtp_cls.return_value = mock_smtp
        client.post(f"/outreach/{fail_message_id}/send-email", follow_redirects=False)

    page = client.get("/outreach")
    failed_section = _section(page.text, "Failed sends")
    assert "SMTP auth failed" in failed_section
    assert "Emails sent today: 1" in page.text  # the failed attempt did not spend quota

    with patch("app.routes.outreach.SMTPEmailClient") as mock_smtp_cls:
        mock_smtp_cls.return_value = MagicMock()
        client.post(f"/outreach/{fail_message_id}/send-email", follow_redirects=False)

    page = client.get("/outreach")
    assert "Emails sent today: 2" in page.text
    failed_section = _section(page.text, "Failed sends")
    assert "No failed sends." in failed_section


def test_mark_sent_rejects_email_channel_message(client):
    from app.db import SessionLocal
    from app.models import OutreachChannel, OutreachMessage

    db = SessionLocal()
    contact = _create_contact(db)
    contact_id = contact.id
    db.close()
    _generate_drafts_for(client, contact_id)

    db = SessionLocal()
    email_message = (
        db.query(OutreachMessage)
        .filter_by(contact_id=contact_id, channel=OutreachChannel.email)
        .first()
    )
    message_id = email_message.id
    db.close()

    response = client.post(f"/outreach/{message_id}/mark-sent", follow_redirects=False)
    assert response.status_code == 400
