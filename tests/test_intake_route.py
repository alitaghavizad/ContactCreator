import asyncio
import io
import json
import time
from unittest.mock import MagicMock, patch

import httpx

from app.cv_parser import CVParseError, StructuredProfile
from app.db import SessionLocal
from app.models import Profile, User


def _mock_claude_response(mock_anthropic_cls, response_text):
    mock_client = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.type = "text"
    mock_content_block.text = response_text
    mock_message = MagicMock()
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    mock_anthropic_cls.return_value = mock_client


@patch("app.routes.intake.anthropic.Anthropic")
def test_submit_intake_creates_profile(mock_anthropic_cls, client):
    _mock_claude_response(
        mock_anthropic_cls,
        '{"skills": ["Java"], "years_experience": 5, "domains": ["banking"], '
        '"target_roles": ["Backend Engineer"], "target_locations": ["Yerevan"], '
        '"seniority": "mid", "tone": "professional"}',
    )

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


@patch("app.routes.intake.parse_cv")
def test_submit_intake_handles_cv_parse_error(mock_parse_cv, client):
    mock_parse_cv.side_effect = CVParseError("bad json")

    cv_file = io.BytesIO(b"Some CV text that Claude fails to parse.")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan",
            "domains": "banking",
            "seniority": "mid",
        },
        files={"cv_file": ("cv.txt", cv_file, "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 502


@patch("app.routes.intake.anthropic.Anthropic")
def test_submit_intake_upserts_single_profile_no_duplicates(mock_anthropic_cls, client):
    # First submission.
    _mock_claude_response(
        mock_anthropic_cls,
        '{"skills": ["Java"], "years_experience": 5, "domains": ["banking"], '
        '"target_roles": ["Backend Engineer"], "target_locations": ["Yerevan"], '
        '"seniority": "mid", "tone": "professional"}',
    )

    cv_file_1 = io.BytesIO(b"5 years Java developer with banking domain experience.")
    response_1 = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan, EU remote",
            "domains": "banking",
            "seniority": "mid",
            "tone": "professional",
        },
        files={"cv_file": ("cv.txt", cv_file_1, "text/plain")},
        follow_redirects=False,
    )
    assert response_1.status_code == 303

    db = SessionLocal()
    try:
        users = db.query(User).all()
        profiles = db.query(Profile).all()
        assert len(users) == 1
        assert len(profiles) == 1

        profile = profiles[0]
        assert profile.cv_text == "5 years Java developer with banking domain experience."
        assert profile.years_experience == 5
        assert json.loads(profile.skills) == ["Java"]
        assert json.loads(profile.domains) == ["banking"]
        assert json.loads(profile.target_roles) == ["Backend Engineer"]
        assert json.loads(profile.target_locations) == ["Yerevan"]
        assert profile.seniority == "mid"
        assert profile.tone == "professional"
    finally:
        db.close()

    # Second submission, different data.
    _mock_claude_response(
        mock_anthropic_cls,
        '{"skills": ["Python", "SQL"], "years_experience": 8, "domains": ["fintech"], '
        '"target_roles": ["Staff Engineer"], "target_locations": ["Remote"], '
        '"seniority": "senior", "tone": "casual"}',
    )

    cv_file_2 = io.BytesIO(b"8 years Python developer with fintech domain experience.")
    response_2 = client.post(
        "/intake",
        data={
            "target_roles": "Staff Engineer",
            "target_locations": "Remote",
            "domains": "fintech",
            "seniority": "senior",
            "tone": "casual",
        },
        files={"cv_file": ("cv2.txt", cv_file_2, "text/plain")},
        follow_redirects=False,
    )
    assert response_2.status_code == 303

    db = SessionLocal()
    try:
        users = db.query(User).all()
        profiles = db.query(Profile).all()
        assert len(users) == 1
        assert len(profiles) == 1

        profile = profiles[0]
        assert profile.cv_text == "8 years Python developer with fintech domain experience."
        assert profile.years_experience == 8
        assert json.loads(profile.skills) == ["Python", "SQL"]
        assert json.loads(profile.domains) == ["fintech"]
        assert json.loads(profile.target_roles) == ["Staff Engineer"]
        assert json.loads(profile.target_locations) == ["Remote"]
        assert profile.seniority == "senior"
        assert profile.tone == "casual"
    finally:
        db.close()


@patch("app.routes.intake.parse_cv")
def test_submit_intake_does_not_block_event_loop(mock_parse_cv, client):
    """The blocking Claude call must run in a threadpool, not on the event loop.

    While /intake is waiting on parse_cv, an unrelated request (/health) must
    still be served promptly. If parse_cv were awaited inline on the event
    loop, /health could not even be dispatched until parse_cv returned.
    """
    parse_delay = 1.0

    def slow_parse(**kwargs):
        time.sleep(parse_delay)
        return StructuredProfile(
            skills=["Java"],
            years_experience=5,
            domains=["banking"],
            target_roles=["Backend Engineer"],
            target_locations=["Yerevan"],
            seniority="mid",
            tone="professional",
        )

    mock_parse_cv.side_effect = slow_parse

    async def scenario():
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            started = time.monotonic()
            intake_task = asyncio.create_task(
                ac.post(
                    "/intake",
                    data={
                        "target_roles": "Backend Engineer",
                        "target_locations": "Yerevan",
                        "domains": "banking",
                        "seniority": "mid",
                    },
                    files={"cv_file": ("cv.txt", io.BytesIO(b"cv text"), "text/plain")},
                    follow_redirects=False,
                )
            )
            # Give the intake request a moment to reach parse_cv. If parse_cv
            # runs on the event loop, this sleep itself cannot resume until it
            # finishes, so elapsed time is measured from before the task start.
            await asyncio.sleep(0.1)

            health = await ac.get("/health")
            health_elapsed = time.monotonic() - started

            intake_response = await intake_task
            return health, health_elapsed, intake_response

    health, health_elapsed, intake_response = asyncio.run(scenario())

    assert health.status_code == 200
    # /health served long before the 1.0s parse_cv call finished.
    assert health_elapsed < parse_delay / 2, (
        f"/health took {health_elapsed:.2f}s - the event loop was blocked by parse_cv"
    )
    assert intake_response.status_code == 303
    assert intake_response.headers["location"] == "/contacts"
