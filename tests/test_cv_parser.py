import io
import json
from unittest.mock import MagicMock

import httpx
import anthropic
import pytest

from app.cv_parser import CVExtractionError, CVParseError, StructuredProfile, extract_pdf_text, parse_cv


def _text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _thinking_block():
    """A non-text block, as Claude may emit before the text block."""
    block = MagicMock()
    block.type = "thinking"
    block.thinking = "Let me look at the CV..."
    del block.text  # a thinking block has no .text attribute at all
    return block


def _mock_anthropic_client(payload: dict):
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [_text_block(json.dumps(payload))]
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_parse_cv_returns_structured_profile():
    payload = {
        "skills": ["Java", "Spring", "AI automation"],
        "years_experience": 5,
        "domains": ["banking", "call-center"],
        "target_roles": ["Backend Engineer", "AI Automation Engineer"],
        "target_locations": ["Yerevan", "EU remote"],
        "seniority": "mid",
        "tone": "professional",
    }
    mock_client = _mock_anthropic_client(payload)

    profile = parse_cv(
        cv_text="5 years Java developer...",
        questionnaire_answers="Targeting backend roles in EU/Armenia",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert isinstance(profile, StructuredProfile)
    assert profile.skills == ["Java", "Spring", "AI automation"]
    assert profile.years_experience == 5
    assert profile.domains == ["banking", "call-center"]
    assert profile.seniority == "mid"

    mock_client.messages.create.assert_called_once()
    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["model"] == "claude-sonnet-5"


def test_parse_cv_defaults_missing_fields():
    mock_client = _mock_anthropic_client({"skills": ["Java"]})

    profile = parse_cv(
        cv_text="short cv",
        questionnaire_answers="",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert profile.years_experience == 0
    assert profile.seniority == "mid"
    assert profile.tone == "professional"


def test_parse_cv_raises_cvparse_error_on_invalid_json():
    """Verify CVParseError is raised when Claude returns non-JSON text."""
    mock_client = MagicMock()
    mock_message = MagicMock()
    # Simulate Claude returning text with JSON embedded but not parseable as-is
    mock_message.content = [_text_block('Sure! Here\'s the profile: {"skills": ["Java"]}')]
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(CVParseError) as exc_info:
        parse_cv(
            cv_text="5 years Java developer...",
            questionnaire_answers="",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "Claude did not return valid JSON" in str(exc_info.value)


def test_parse_cv_skips_non_text_content_blocks():
    """A thinking block before the text block must not break extraction."""
    payload = {
        "skills": ["Java"],
        "years_experience": 5,
        "domains": ["banking"],
        "target_roles": ["Backend Engineer"],
        "target_locations": ["Yerevan"],
        "seniority": "mid",
        "tone": "professional",
    }
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [_thinking_block(), _text_block(json.dumps(payload))]
    mock_client.messages.create.return_value = mock_message

    profile = parse_cv(
        cv_text="5 years Java developer...",
        questionnaire_answers="",
        client=mock_client,
        model="claude-sonnet-5",
    )

    assert profile.skills == ["Java"]
    assert profile.years_experience == 5
    assert profile.target_roles == ["Backend Engineer"]


def test_parse_cv_raises_when_no_text_block_present():
    """Empty / text-free content raises CVParseError instead of IndexError."""
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = []
    mock_client.messages.create.return_value = mock_message

    with pytest.raises(CVParseError) as exc_info:
        parse_cv(
            cv_text="cv",
            questionnaire_answers="",
            client=mock_client,
            model="claude-sonnet-5",
        )

    assert "no text content block" in str(exc_info.value)

    mock_message.content = [_thinking_block()]
    with pytest.raises(CVParseError):
        parse_cv(
            cv_text="cv",
            questionnaire_answers="",
            client=mock_client,
            model="claude-sonnet-5",
        )


def test_parse_cv_requests_headroom_max_tokens():
    mock_client = _mock_anthropic_client({"skills": ["Java"]})

    parse_cv(
        cv_text="cv",
        questionnaire_answers="",
        client=mock_client,
        model="claude-sonnet-5",
    )

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["max_tokens"] == 2048


def test_extract_pdf_text_concatenates_pages(monkeypatch):
    from unittest.mock import MagicMock

    import app.cv_parser as cv_parser_module

    page1 = MagicMock()
    page1.extract_text.return_value = "Page one text."
    page2 = MagicMock()
    page2.extract_text.return_value = "Page two text."
    mock_reader = MagicMock()
    mock_reader.pages = [page1, page2]

    monkeypatch.setattr(
        cv_parser_module, "PdfReader", lambda _stream: mock_reader
    )

    result = extract_pdf_text(b"fake pdf bytes")

    assert result == "Page one text.\nPage two text."


def test_extract_pdf_text_skips_pages_with_no_text(monkeypatch):
    from unittest.mock import MagicMock

    import app.cv_parser as cv_parser_module

    page_with_text = MagicMock()
    page_with_text.extract_text.return_value = "Some text."
    page_without_text = MagicMock()
    page_without_text.extract_text.return_value = None
    mock_reader = MagicMock()
    mock_reader.pages = [page_without_text, page_with_text]

    monkeypatch.setattr(
        cv_parser_module, "PdfReader", lambda _stream: mock_reader
    )

    result = extract_pdf_text(b"fake pdf bytes")

    assert result == "Some text."


def test_extract_pdf_text_raises_when_no_text_on_any_page(monkeypatch):
    from unittest.mock import MagicMock

    import app.cv_parser as cv_parser_module

    page = MagicMock()
    page.extract_text.return_value = ""
    mock_reader = MagicMock()
    mock_reader.pages = [page]

    monkeypatch.setattr(
        cv_parser_module, "PdfReader", lambda _stream: mock_reader
    )

    with pytest.raises(CVExtractionError) as exc_info:
        extract_pdf_text(b"fake pdf bytes")

    assert "no text" in str(exc_info.value).lower()


def test_extract_pdf_text_raises_on_corrupt_pdf():
    with pytest.raises(CVExtractionError) as exc_info:
        extract_pdf_text(b"%PDF-1.4 not a real pdf")

    assert "could not read" in str(exc_info.value).lower()


def test_extract_pdf_text_raises_on_parse_error(monkeypatch):
    from unittest.mock import MagicMock

    import app.cv_parser as cv_parser_module
    from pypdf.errors import ParseError

    def mock_pdf_reader_raises_parse_error(_stream):
        raise ParseError("simulated parse error")

    monkeypatch.setattr(
        cv_parser_module, "PdfReader", mock_pdf_reader_raises_parse_error
    )

    with pytest.raises(CVExtractionError) as exc_info:
        extract_pdf_text(b"fake pdf bytes")

    assert "could not read" in str(exc_info.value).lower()


def test_extract_pdf_text_raises_on_dependency_error(monkeypatch):
    from unittest.mock import MagicMock

    import app.cv_parser as cv_parser_module
    from pypdf.errors import DependencyError

    def mock_pdf_reader_raises_dependency_error(_stream):
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(
        cv_parser_module, "PdfReader", mock_pdf_reader_raises_dependency_error
    )

    with pytest.raises(CVExtractionError) as exc_info:
        extract_pdf_text(b"fake pdf bytes")

    assert "could not read" in str(exc_info.value).lower()


def test_parse_cv_raises_cvparse_error_on_anthropic_api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(CVParseError):
        parse_cv(
            cv_text="5 years Java developer...",
            questionnaire_answers="",
            client=mock_client,
            model="claude-sonnet-5",
        )
