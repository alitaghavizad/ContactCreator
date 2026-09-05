from unittest.mock import MagicMock

from app.drafting import LINKEDIN_CHAR_LIMIT, draft_email, draft_linkedin_note


def _mock_client(response_text: str):
    mock_client = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = response_text
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_draft_linkedin_note_returns_text_within_limit():
    mock_client = _mock_client("Hi Jane, saw your work leading platform teams at Example Bank...")

    note = draft_linkedin_note(
        profile_summary="5 years Java, banking domain expertise",
        contact_name="Jane Doe",
        contact_title="Engineering Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert len(note) <= LINKEDIN_CHAR_LIMIT
    assert "Jane" in note


def test_draft_linkedin_note_truncates_oversized_response():
    overly_long = "x" * 500
    mock_client = _mock_client(overly_long)

    note = draft_linkedin_note(
        profile_summary="summary",
        contact_name="Jane",
        contact_title="Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert len(note) == LINKEDIN_CHAR_LIMIT


def test_draft_email_returns_stripped_text():
    mock_client = _mock_client("  Hi Jane,\n\nI noticed...  ")

    email = draft_email(
        profile_summary="5 years Java, banking domain expertise",
        contact_name="Jane Doe",
        contact_title="Engineering Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert email == "Hi Jane,\n\nI noticed..."
    mock_client.messages.create.assert_called_once()
