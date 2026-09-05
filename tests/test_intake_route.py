import io
from unittest.mock import MagicMock, patch


@patch("app.routes.intake.anthropic.Anthropic")
def test_submit_intake_creates_profile(mock_anthropic_cls, client):
    mock_client = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = (
        '{"skills": ["Java"], "years_experience": 5, "domains": ["banking"], '
        '"target_roles": ["Backend Engineer"], "target_locations": ["Yerevan"], '
        '"seniority": "mid", "tone": "professional"}'
    )
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    mock_anthropic_cls.return_value = mock_client

    cv_file = io.BytesIO(b"5 years Java developer with banking domain experience.")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan, EU remote",
            "domains": "banking",
            "seniority": "mid",
            "tone": "professional",
        },
        files={"cv_file": ("cv.txt", cv_file, "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/contacts"


def test_submit_intake_rejects_non_txt_file(client):
    cv_file = io.BytesIO(b"%PDF-1.4 fake pdf content")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan",
            "domains": "banking",
            "seniority": "mid",
        },
        files={"cv_file": ("cv.pdf", cv_file, "application/pdf")},
    )

    assert response.status_code == 400
