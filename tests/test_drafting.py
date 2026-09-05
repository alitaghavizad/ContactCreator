from unittest.mock import MagicMock

import pytest

from app.drafting import (
    LINKEDIN_CHAR_LIMIT,
    DraftingError,
    draft_email,
    draft_email_subject,
    draft_linkedin_note,
)


def _text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _thinking_block():
    """A non-text block, as Claude may emit before the text block."""
    block = MagicMock()
    block.type = "thinking"
    block.thinking = "Considering how to phrase this..."
    del block.text  # a thinking block has no .text attribute at all
    return block


def _mock_client(response_text: str):
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [_text_block(response_text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


def _mock_client_with_blocks(blocks):
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = blocks
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


def test_draft_linkedin_note_skips_non_text_content_blocks():
    mock_client = _mock_client_with_blocks(
        [_thinking_block(), _text_block("Hi Jane, your platform work at Example Bank...")]
    )

    note = draft_linkedin_note(
        profile_summary="5 years Java, banking domain expertise",
        contact_name="Jane Doe",
        contact_title="Engineering Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert note == "Hi Jane, your platform work at Example Bank..."


def test_draft_email_skips_non_text_content_blocks():
    mock_client = _mock_client_with_blocks(
        [_thinking_block(), _text_block("  Hi Jane,\n\nI noticed...  ")]
    )

    email = draft_email(
        profile_summary="5 years Java, banking domain expertise",
        contact_name="Jane Doe",
        contact_title="Engineering Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert email == "Hi Jane,\n\nI noticed..."


def test_draft_linkedin_note_raises_when_only_non_text_blocks():
    mock_client = _mock_client_with_blocks([_thinking_block()])

    with pytest.raises(DraftingError) as exc_info:
        draft_linkedin_note(
            profile_summary="summary",
            contact_name="Jane",
            contact_title="Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "no text content block" in str(exc_info.value)


def test_draft_email_raises_when_only_non_text_blocks():
    mock_client = _mock_client_with_blocks([_thinking_block()])

    with pytest.raises(DraftingError) as exc_info:
        draft_email(
            profile_summary="summary",
            contact_name="Jane",
            contact_title="Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "no text content block" in str(exc_info.value)


def test_draft_calls_request_headroom_max_tokens():
    mock_client = _mock_client("note text")
    draft_linkedin_note(
        profile_summary="summary",
        contact_name="Jane",
        contact_title="Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["max_tokens"] == 500

    mock_client = _mock_client("email text")
    draft_email(
        profile_summary="summary",
        contact_name="Jane",
        contact_title="Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["max_tokens"] == 1200


def test_draft_linkedin_note_raises_on_empty_content():
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = []
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(DraftingError) as exc_info:
        draft_linkedin_note(
            profile_summary="5 years Java, banking domain expertise",
            contact_name="Jane Doe",
            contact_title="Engineering Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "empty response" in str(exc_info.value)


def test_draft_email_raises_on_empty_content():
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = []
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(DraftingError) as exc_info:
        draft_email(
            profile_summary="5 years Java, banking domain expertise",
            contact_name="Jane Doe",
            contact_title="Engineering Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "empty response" in str(exc_info.value)


def test_draft_email_subject_returns_stripped_text():
    mock_client = _mock_client("  Backend engineer with banking domain background  ")

    subject = draft_email_subject(
        profile_summary="5 years Java, banking domain expertise",
        contact_name="Jane Doe",
        contact_title="Engineering Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert subject == "Backend engineer with banking domain background"
    mock_client.messages.create.assert_called_once()


def test_draft_email_subject_skips_non_text_content_blocks():
    mock_client = _mock_client_with_blocks(
        [_thinking_block(), _text_block("Quick question about your platform team")]
    )

    subject = draft_email_subject(
        profile_summary="summary",
        contact_name="Jane",
        contact_title="Manager",
        company_name="Example Bank",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert subject == "Quick question about your platform team"


def test_draft_email_subject_raises_on_empty_content():
    mock_client = _mock_client_with_blocks([])

    with pytest.raises(DraftingError):
        draft_email_subject(
            profile_summary="summary",
            contact_name="Jane",
            contact_title="Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )
