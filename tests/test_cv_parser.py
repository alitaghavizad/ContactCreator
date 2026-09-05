import json
from unittest.mock import MagicMock

from app.cv_parser import StructuredProfile, parse_cv


def _mock_anthropic_client(payload: dict):
    mock_client = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = json.dumps(payload)
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
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
