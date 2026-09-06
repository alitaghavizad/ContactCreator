from unittest.mock import patch

import pytest

from app.db import SessionLocal
from app.models import OutreachChannel, OutreachMessage, OutreachStatus
from tests.test_outreach_route import _create_contact


def make_draft(channel=OutreachChannel.email, status=OutreachStatus.drafted):
    with SessionLocal() as db:
        contact = _create_contact(db)
        message = OutreachMessage(contact_id=contact.id, channel=channel,
                                  draft_text="Original body", subject="Original subject", status=status)
        db.add(message)
        db.commit()
        return message.id


def test_ui_pages_and_assets_render_with_empty_database(client):
    for path in ("/", "/contacts", "/outreach", "/intake"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'aria-label="Main navigation"' in response.text
        assert '/static/app.css' in response.text
    for path in ("/static/app.css", "/static/app.js", "/static/favicon.svg"):
        assert client.get(path).status_code == 200


def test_saved_draft_survives_reload_and_send(client):
    message_id = make_draft()
    response = client.post(f"/outreach/{message_id}/edit", data={
        "draft_text": "  My personal introduction.\n\nBest,\nAli  ", "subject": "A personal hello",
    })
    assert response.status_code == 200
    assert "My personal introduction." in response.text
    with patch("app.routes.outreach.SMTPEmailClient") as smtp:
        client.post(f"/outreach/{message_id}/send-email", follow_redirects=False)
        smtp.return_value.send.assert_called_once_with(
            "jane@example.com", "A personal hello", "My personal introduction.\n\nBest,\nAli")


def test_send_uses_current_editor_values_without_separate_save(client):
    message_id = make_draft()
    with patch("app.routes.outreach.SMTPEmailClient") as smtp:
        response = client.post(f"/outreach/{message_id}/send-email", data={
            "draft_text": "Latest edit", "subject": "Latest subject",
        }, follow_redirects=False)
        assert response.status_code == 303
        smtp.return_value.send.assert_called_once_with("jane@example.com", "Latest subject", "Latest edit")
    with SessionLocal() as db:
        assert db.get(OutreachMessage, message_id).draft_text == "Latest edit"


@pytest.mark.parametrize("status", [OutreachStatus.sent, OutreachStatus.replied, OutreachStatus.interview])
def test_sent_history_cannot_be_edited(client, status):
    message_id = make_draft(status=status)
    response = client.post(f"/outreach/{message_id}/edit", data={"draft_text": "Overwrite"})
    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.get(OutreachMessage, message_id).draft_text == "Original body"


@pytest.mark.parametrize("text,subject", [("   ", "Subject"), ("Body", "Header\r\nInjected")])
def test_invalid_email_edits_are_not_saved_or_sent(client, text, subject):
    message_id = make_draft()
    with patch("app.routes.outreach.SMTPEmailClient") as smtp:
        for action in ("edit", "send-email"):
            response = client.post(f"/outreach/{message_id}/{action}", data={"draft_text": text, "subject": subject})
            assert response.status_code == 400
        smtp.assert_not_called()
    with SessionLocal() as db:
        assert db.get(OutreachMessage, message_id).draft_text == "Original body"


def test_linkedin_length_limit_and_failed_draft_editing(client):
    message_id = make_draft(channel=OutreachChannel.linkedin)
    assert client.post(f"/outreach/{message_id}/edit", data={"draft_text": "a" * 301}).status_code == 400
    assert client.post(f"/outreach/{message_id}/edit", data={"draft_text": "a" * 300}).status_code == 200
    failed_id = make_draft(status=OutreachStatus.failed)
    assert client.post(f"/outreach/{failed_id}/edit", data={"draft_text": "Fixed"}).status_code == 200
    assert client.post("/outreach/999999/edit", data={"draft_text": "Missing"}).status_code == 404


def test_overview_counts_actual_records(client):
    make_draft(status=OutreachStatus.sent)
    make_draft(status=OutreachStatus.replied)
    make_draft(status=OutreachStatus.interview)
    make_draft()
    response = client.get("/")
    assert response.status_code == 200
    assert '1 draft ready for your review' in response.text
    assert '67%' in response.text
    assert 'width: 66.666' in response.text


def test_mark_linkedin_sent_preserves_the_edited_note(client):
    message_id = make_draft(channel=OutreachChannel.linkedin)
    response = client.post(f"/outreach/{message_id}/mark-sent", data={"draft_text": "The note I copied and sent"}, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        message = db.get(OutreachMessage, message_id)
        assert message.draft_text == "The note I copied and sent"
        assert message.status == OutreachStatus.sent
