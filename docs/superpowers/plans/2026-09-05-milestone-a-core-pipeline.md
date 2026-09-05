# Milestone A: Core Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core, usable slice of ContactCreator: upload a CV + answer a few questions, automatically discover relevant people via Apollo.io, generate personalized LinkedIn/email drafts via Claude, and review them in a queue — without needing email auto-send, follow-up tracking, or auth (those are later milestones).

**Architecture:** A single FastAPI app (server-rendered Jinja2 templates, no SPA framework) backed by Postgres in production (via Docker Compose) and SQLite in-memory for tests. Business logic (Apollo query building, credit tracking, CV parsing, message drafting) lives in plain, dependency-injected modules under `app/` that are unit-tested with the Claude/Apollo HTTP calls mocked — no live API calls happen in the test suite.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (synchronous), PostgreSQL 16, Jinja2, `anthropic` SDK (Claude), `httpx` (Apollo HTTP calls), pytest, Docker Compose.

## Global Constraints

- Every table carries the FK columns needed for future multi-user support (`user_id`), even though this plan only ever creates one implicit `User` row. This is required by the approved spec (`docs/superpowers/specs/2026-09-05-contact-creator-phase1-design.md`) so Phase 2 (auth) is additive.
- No automation touches LinkedIn directly. LinkedIn drafts are generated and displayed for manual copy/paste; the app never sends anything to LinkedIn. This is a hard requirement from the spec (ToS/ban risk).
- Apollo.io free tier only. Credit usage must be tracked and searches must be blocked (not silently over-spent) once the configured monthly limit is reached.
- CV upload accepts plain-text `.txt` files only in this plan. PDF parsing is explicitly deferred (not needed for the core pipeline to work end-to-end; adding a PDF-text-extraction step is a self-contained fast-follow).
- No authentication/login in this plan. A single default `User` row stands in for "you."
- Tests never call live Apollo or Claude APIs — always mock at the HTTP/SDK boundary. Tests run via plain `pytest` against SQLite in-memory, no Docker required.
- Every task ends with `pytest` passing before its commit.
- Claude model name is configurable via the `CLAUDE_MODEL` env var, default `claude-sonnet-5`.

## Not Built In This Plan (deferred to later milestones — see spec)

- Milestone B: follow-up dashboard, funnel counts, manual reply-status updates, `Event` logging wired into business logic (the `events` table is created now but unused until Milestone B).
- Milestone C: actual email sending (Gmail/SMTP), daily send caps.
- Milestone D: broader test coverage, polished error handling, README/setup docs, PDF CV support.
- Authentication and multi-user UI (Phase 2 in the spec).

## How to Run Things (for whoever picks this up)

**Run the app:**
```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and APOLLO_API_KEY in .env
docker compose up --build
```
Then visit `http://localhost:8000/intake`.

**Run the tests (no Docker needed):**
```bash
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
pytest -v
```

**Progress tracking:** every task below has checkboxes. If you are resuming this plan, scroll down to the first unchecked box — everything above it is done and committed. Run `git log --oneline` to see the matching commits.

---

### Task 1: Project Scaffolding + Health Endpoint

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Produces: `app.config.settings` (object with `.database_url`, `.anthropic_api_key`, `.claude_model`, `.apollo_api_key`, `.apollo_monthly_credit_limit`); `app.main.app` (the FastAPI instance); a pytest `client` fixture (from `tests/conftest.py`) usable by all later route tests.

- [ ] **Step 1: Create scaffolding files**

`requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
psycopg2-binary==2.9.10
pydantic==2.9.2
python-multipart==0.0.12
jinja2==3.1.4
anthropic==0.39.0
httpx==0.27.2
python-dotenv==1.0.1
pytest==8.3.3
pytest-mock==3.14.0
```

`Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml`:
```yaml
version: "3.9"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db
    volumes:
      - ./app:/app/app

  db:
    image: postgres:16
    environment:
      POSTGRES_USER: contactcreator
      POSTGRES_PASSWORD: contactcreator
      POSTGRES_DB: contactcreator
    ports:
      - "5432:5432"
    volumes:
      - db_data:/var/lib/postgresql/data

volumes:
  db_data:
```

`.env.example`:
```
DATABASE_URL=postgresql://contactcreator:contactcreator@db:5432/contactcreator
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-5
APOLLO_API_KEY=
APOLLO_MONTHLY_CREDIT_LIMIT=60
```

`app/__init__.py`: (empty file)

`app/config.py`:
```python
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://contactcreator:contactcreator@db:5432/contactcreator"
    )
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
    apollo_api_key: str = os.environ.get("APOLLO_API_KEY", "")
    apollo_monthly_credit_limit: int = int(os.environ.get("APOLLO_MONTHLY_CREDIT_LIMIT", "60"))


settings = Settings()
```

`tests/__init__.py`: (empty file)

`tests/conftest.py`:
```python
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("APOLLO_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **Step 2: Write the failing test**

`tests/test_health.py`:
```python
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Implement app/main.py**

`app/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="ContactCreator")


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml .env.example app tests
git commit -m "feat: project scaffolding and health endpoint"
```

---

### Task 2: Database Models & Connection

**Files:**
- Create: `app/db.py`
- Create: `app/models.py`
- Modify: `app/main.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.settings.database_url` (Task 1).
- Produces: `app.db.engine`, `app.db.SessionLocal`, `app.db.get_db()` (FastAPI dependency generator); `app.models.Base`; ORM classes `User(email)`, `Profile(user_id, cv_text, skills, years_experience, domains, target_roles, target_locations, seniority, tone)`, `Company(name, domain, location, industry, source)`, `Contact(user_id, company_id, name, title, linkedin_url, email, discovery_source)`, `OutreachMessage(contact_id, channel, draft_text, status, sent_at, follow_up_due_at)`, `Event(contact_id, type, note, timestamp)`; enums `OutreachChannel.{linkedin,email}`, `OutreachStatus.{drafted,sent,replied,no_response,interview,rejected,failed}`. `User.profile` is a one-to-one relationship back to `Profile`. `skills`, `domains`, `target_roles`, `target_locations` are stored as JSON-encoded text (via `json.dumps`/`json.loads` at the call site, not inside the model).

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models import Base, Profile, User


def test_create_user_and_profile():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        user = User(email="ali@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)

        profile = Profile(
            user_id=user.id,
            cv_text="Experienced Java developer...",
            skills='["Java", "Spring"]',
            years_experience=5,
            domains='["banking", "call-center"]',
            target_roles='["Backend Engineer"]',
            target_locations='["Yerevan", "EU remote"]',
            seniority="mid-senior",
            tone="professional",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

        fetched = db.query(Profile).filter_by(user_id=user.id).first()
        assert fetched is not None
        assert fetched.cv_text.startswith("Experienced Java developer")
        assert fetched.years_experience == 5
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Implement app/db.py**

`app/db.py`:
```python
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://contactcreator:contactcreator@db:5432/contactcreator"
)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Implement app/models.py**

`app/models.py`:
```python
import enum
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class OutreachChannel(str, enum.Enum):
    linkedin = "linkedin"
    email = "email"


class OutreachStatus(str, enum.Enum):
    drafted = "drafted"
    sent = "sent"
    replied = "replied"
    no_response = "no_response"
    interview = "interview"
    rejected = "rejected"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    profile = relationship("Profile", back_populates="user", uselist=False)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cv_text = Column(Text, nullable=False)
    skills = Column(Text)
    years_experience = Column(Integer)
    domains = Column(Text)
    target_roles = Column(Text)
    target_locations = Column(Text)
    seniority = Column(String)
    tone = Column(String)

    user = relationship("User", back_populates="profile")


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    domain = Column(String)
    location = Column(String)
    industry = Column(String)
    source = Column(String, default="apollo")


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String)
    linkedin_url = Column(String)
    email = Column(String)
    discovery_source = Column(String, default="apollo")

    company = relationship("Company")


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    channel = Column(SAEnum(OutreachChannel), nullable=False)
    draft_text = Column(Text, nullable=False)
    status = Column(SAEnum(OutreachStatus), default=OutreachStatus.drafted)
    sent_at = Column(DateTime, nullable=True)
    follow_up_due_at = Column(DateTime, nullable=True)

    contact = relationship("Contact")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    type = Column(String, nullable=False)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: Wire table creation into app startup**

Modify `app/main.py` to:
```python
from fastapi import FastAPI

from app.db import engine
from app.models import Base

app = FastAPI(title="ContactCreator")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 7: Make the test client reset the schema before each test**

Modify `tests/conftest.py`'s `client` fixture to:
```python
@pytest.fixture
def client():
    from app.db import engine
    from app.main import app
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **Step 8: Run the full test suite to verify nothing broke**

Run: `pytest -v`
Expected: PASS (both `test_health.py` and `test_models.py`)

- [ ] **Step 9: Commit**

```bash
git add app/db.py app/models.py app/main.py tests/conftest.py tests/test_models.py
git commit -m "feat: add database models and connection"
```

---

### Task 3: Apollo.io Client + Credit Tracker

**Files:**
- Create: `app/apollo_client.py`
- Create: `app/credit_tracker.py`
- Test: `tests/test_apollo_client.py`
- Test: `tests/test_credit_tracker.py`

**Interfaces:**
- Produces: `app.apollo_client.SearchCriteria(titles: list[str], locations: list[str], industries: list[str] = [], per_page: int = 25)`; `app.apollo_client.ApolloPerson(name, title, company_name, company_domain, linkedin_url, email)`; `app.apollo_client.build_search_params(criteria) -> dict`; `app.apollo_client.ApolloClient(api_key: str, http_client: httpx.Client | None = None).search_people(criteria) -> list[ApolloPerson]`. `app.credit_tracker.CreditTracker(limit: int, used: int = 0, period_start: date | None = None)` with `.remaining() -> int`, `.can_spend(amount) -> bool`, `.spend(amount)` (raises `CreditLimitExceededError` if insufficient), `.reset_if_new_period(today: date, period_length_days: int = 30)`.

- [ ] **Step 1: Write the failing tests for the query builder and client**

`tests/test_apollo_client.py`:
```python
from unittest.mock import MagicMock

import httpx

from app.apollo_client import ApolloClient, SearchCriteria, build_search_params


def test_build_search_params_includes_titles_and_locations():
    criteria = SearchCriteria(titles=["Engineering Manager"], locations=["Yerevan", "EU remote"])

    params = build_search_params(criteria)

    assert params["person_titles"] == ["Engineering Manager"]
    assert params["person_locations"] == ["Yerevan", "EU remote"]
    assert params["per_page"] == 25
    assert "organization_industry_tag_ids" not in params


def test_build_search_params_includes_industries_when_given():
    criteria = SearchCriteria(titles=["Recruiter"], locations=["Armenia"], industries=["banking"])

    params = build_search_params(criteria)

    assert params["organization_industry_tag_ids"] == ["banking"]


def test_search_people_parses_response_into_apollo_person():
    mock_http = MagicMock(spec=httpx.Client)
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "people": [
            {
                "name": "Jane Doe",
                "title": "Engineering Manager",
                "linkedin_url": "https://linkedin.com/in/janedoe",
                "email": "jane@example.com",
                "organization": {"name": "Example Bank", "primary_domain": "example.com"},
            }
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_http.post.return_value = mock_response

    client = ApolloClient(api_key="test-key", http_client=mock_http)
    criteria = SearchCriteria(titles=["Engineering Manager"], locations=["Yerevan"])

    results = client.search_people(criteria)

    assert len(results) == 1
    person = results[0]
    assert person.name == "Jane Doe"
    assert person.company_name == "Example Bank"
    assert person.company_domain == "example.com"
    assert person.linkedin_url == "https://linkedin.com/in/janedoe"
    assert person.email == "jane@example.com"

    mock_http.post.assert_called_once()
    _, kwargs = mock_http.post.call_args
    assert kwargs["headers"]["x-api-key"] == "test-key"
```

`tests/test_credit_tracker.py`:
```python
from datetime import date, timedelta

import pytest

from app.credit_tracker import CreditLimitExceededError, CreditTracker


def test_remaining_starts_at_full_limit():
    tracker = CreditTracker(limit=60)
    assert tracker.remaining() == 60


def test_spend_reduces_remaining():
    tracker = CreditTracker(limit=60)
    tracker.spend(25)
    assert tracker.remaining() == 35
    assert tracker.used == 25


def test_spend_raises_when_exceeding_limit():
    tracker = CreditTracker(limit=10, used=8)
    with pytest.raises(CreditLimitExceededError):
        tracker.spend(5)
    assert tracker.used == 8


def test_can_spend_returns_false_when_insufficient():
    tracker = CreditTracker(limit=10, used=10)
    assert tracker.can_spend(1) is False


def test_reset_if_new_period_resets_after_30_days():
    start = date(2026, 1, 1)
    tracker = CreditTracker(limit=60, used=60, period_start=start)

    tracker.reset_if_new_period(today=start + timedelta(days=30))

    assert tracker.used == 0
    assert tracker.period_start == start + timedelta(days=30)


def test_reset_if_new_period_keeps_usage_within_period():
    start = date(2026, 1, 1)
    tracker = CreditTracker(limit=60, used=20, period_start=start)

    tracker.reset_if_new_period(today=start + timedelta(days=10))

    assert tracker.used == 20
    assert tracker.period_start == start
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_apollo_client.py tests/test_credit_tracker.py -v`
Expected: FAIL with `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Implement app/apollo_client.py**

`app/apollo_client.py`:
```python
from dataclasses import dataclass, field
from typing import Optional

import httpx

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/search"


@dataclass
class SearchCriteria:
    titles: list[str]
    locations: list[str]
    industries: list[str] = field(default_factory=list)
    per_page: int = 25


@dataclass
class ApolloPerson:
    name: str
    title: Optional[str]
    company_name: Optional[str]
    company_domain: Optional[str]
    linkedin_url: Optional[str]
    email: Optional[str]


def build_search_params(criteria: SearchCriteria) -> dict:
    """Translate intake criteria into Apollo's mixed_people/search request body.

    Field names follow Apollo's documented People Search API as of this
    writing; verify against https://apolloio.github.io/apollo-api-docs/
    if Apollo has changed their schema since.
    """
    params: dict = {
        "person_titles": criteria.titles,
        "person_locations": criteria.locations,
        "per_page": criteria.per_page,
        "page": 1,
    }
    if criteria.industries:
        params["organization_industry_tag_ids"] = criteria.industries
    return params


class ApolloClient:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None):
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=30.0)

    def search_people(self, criteria: SearchCriteria) -> list[ApolloPerson]:
        params = build_search_params(criteria)
        response = self._http.post(
            APOLLO_SEARCH_URL,
            json=params,
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return [_to_apollo_person(p) for p in data.get("people", [])]


def _to_apollo_person(raw: dict) -> ApolloPerson:
    organization = raw.get("organization") or {}
    return ApolloPerson(
        name=raw.get("name", ""),
        title=raw.get("title"),
        company_name=organization.get("name"),
        company_domain=organization.get("primary_domain"),
        linkedin_url=raw.get("linkedin_url"),
        email=raw.get("email"),
    )
```

- [ ] **Step 4: Implement app/credit_tracker.py**

`app/credit_tracker.py`:
```python
from dataclasses import dataclass
from datetime import date
from typing import Optional


class CreditLimitExceededError(Exception):
    pass


@dataclass
class CreditUsage:
    used: int
    limit: int
    period_start: date


class CreditTracker:
    """Tracks Apollo.io credit usage within the current monthly period.

    This class only implements the counting rules, in memory, so they can
    be unit tested without a database. Callers (the discovery route) are
    responsible for loading/saving the used count and period_start.
    """

    def __init__(self, limit: int, used: int = 0, period_start: Optional[date] = None):
        self.limit = limit
        self.used = used
        self.period_start = period_start or date.today()

    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    def can_spend(self, amount: int) -> bool:
        return self.remaining() >= amount

    def spend(self, amount: int) -> None:
        if not self.can_spend(amount):
            raise CreditLimitExceededError(
                f"Requested {amount} credits but only {self.remaining()} remain "
                f"out of {self.limit} this period."
            )
        self.used += amount

    def reset_if_new_period(self, today: date, period_length_days: int = 30) -> None:
        if (today - self.period_start).days >= period_length_days:
            self.used = 0
            self.period_start = today
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_apollo_client.py tests/test_credit_tracker.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/apollo_client.py app/credit_tracker.py tests/test_apollo_client.py tests/test_credit_tracker.py
git commit -m "feat: add Apollo.io client and credit tracker"
```

---

### Task 4: CV Parsing via Claude

**Files:**
- Create: `app/cv_parser.py`
- Test: `tests/test_cv_parser.py`

**Interfaces:**
- Produces: `app.cv_parser.StructuredProfile` (dataclass: `skills: list[str]`, `years_experience: int`, `domains: list[str]`, `target_roles: list[str]`, `target_locations: list[str]`, `seniority: str`, `tone: str`); `app.cv_parser.parse_cv(cv_text: str, questionnaire_answers: str, client: anthropic.Anthropic, model: str) -> StructuredProfile`.

- [ ] **Step 1: Write the failing test**

`tests/test_cv_parser.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cv_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cv_parser'`

- [ ] **Step 3: Implement app/cv_parser.py**

`app/cv_parser.py`:
```python
import json
from dataclasses import dataclass, field

import anthropic

CV_PARSE_SYSTEM_PROMPT = """You are a resume-parsing assistant. Read the candidate's CV \
and the answers they gave to a short intake questionnaire, then return ONLY a JSON object \
(no prose, no markdown fences) with these exact keys:

- "skills": list of strings, key technical skills
- "years_experience": integer, total years of professional software experience
- "domains": list of strings, domain expertise (e.g. "banking", "call-center")
- "target_roles": list of strings, job titles the candidate is targeting
- "target_locations": list of strings, locations/work-arrangements the candidate is targeting
- "seniority": string, one of "junior", "mid", "senior", "lead"
- "tone": string, one of "formal", "professional", "casual"
"""


@dataclass
class StructuredProfile:
    skills: list[str] = field(default_factory=list)
    years_experience: int = 0
    domains: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    target_locations: list[str] = field(default_factory=list)
    seniority: str = "mid"
    tone: str = "professional"


def parse_cv(
    cv_text: str,
    questionnaire_answers: str,
    client: anthropic.Anthropic,
    model: str,
) -> StructuredProfile:
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=CV_PARSE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"CV:\n{cv_text}\n\n"
                    f"Questionnaire answers:\n{questionnaire_answers}"
                ),
            }
        ],
    )
    raw_text = message.content[0].text
    data = json.loads(raw_text)
    return StructuredProfile(
        skills=data.get("skills", []),
        years_experience=int(data.get("years_experience", 0)),
        domains=data.get("domains", []),
        target_roles=data.get("target_roles", []),
        target_locations=data.get("target_locations", []),
        seniority=data.get("seniority", "mid"),
        tone=data.get("tone", "professional"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cv_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cv_parser.py tests/test_cv_parser.py
git commit -m "feat: add CV parsing via Claude"
```

---

### Task 5: Message Drafting via Claude

**Files:**
- Create: `app/drafting.py`
- Test: `tests/test_drafting.py`

**Interfaces:**
- Produces: `app.drafting.LINKEDIN_CHAR_LIMIT` (int, 300); `app.drafting.draft_linkedin_note(profile_summary: str, contact_name: str, contact_title: str, company_name: str, client: anthropic.Anthropic, model: str) -> str` (guaranteed `len(result) <= LINKEDIN_CHAR_LIMIT`); `app.drafting.draft_email(profile_summary: str, contact_name: str, contact_title: str, company_name: str, client: anthropic.Anthropic, model: str) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_drafting.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drafting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.drafting'`

- [ ] **Step 3: Implement app/drafting.py**

`app/drafting.py`:
```python
import anthropic

LINKEDIN_CHAR_LIMIT = 300

LINKEDIN_SYSTEM_PROMPT = """You write short, specific LinkedIn connection notes for a job \
seeker reaching out to someone in their target industry. The note must be under {limit} \
characters, reference something concrete from the candidate's background, and avoid generic \
phrases like "I'd love to connect" with no substance. Return ONLY the note text, no quotes, \
no markdown."""

EMAIL_SYSTEM_PROMPT = """You write short, specific cold outreach emails for a job seeker \
reaching out to someone in their target industry. The email should be 3-5 short paragraphs, \
reference something concrete about the candidate's background and the recipient's company, \
and end with a clear, low-pressure call to action (e.g. a 15-minute chat). Return ONLY the \
email body text, no subject line, no markdown."""


def draft_linkedin_note(
    profile_summary: str,
    contact_name: str,
    contact_title: str,
    company_name: str,
    client: anthropic.Anthropic,
    model: str,
) -> str:
    system = LINKEDIN_SYSTEM_PROMPT.format(limit=LINKEDIN_CHAR_LIMIT)
    message = client.messages.create(
        model=model,
        max_tokens=200,
        system=system,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Candidate background:\n{profile_summary}\n\n"
                    f"Recipient: {contact_name}, {contact_title} at {company_name}"
                ),
            }
        ],
    )
    note = message.content[0].text.strip()
    return note[:LINKEDIN_CHAR_LIMIT]


def draft_email(
    profile_summary: str,
    contact_name: str,
    contact_title: str,
    company_name: str,
    client: anthropic.Anthropic,
    model: str,
) -> str:
    message = client.messages.create(
        model=model,
        max_tokens=600,
        system=EMAIL_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Candidate background:\n{profile_summary}\n\n"
                    f"Recipient: {contact_name}, {contact_title} at {company_name}"
                ),
            }
        ],
    )
    return message.content[0].text.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drafting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/drafting.py tests/test_drafting.py
git commit -m "feat: add message drafting via Claude"
```

---

### Task 6: Intake Route + Form

**Files:**
- Create: `app/routes/__init__.py`
- Create: `app/routes/intake.py`
- Create: `app/templates/intake.html`
- Modify: `app/main.py`
- Test: `tests/test_intake_route.py`

**Interfaces:**
- Consumes: `app.cv_parser.parse_cv` (Task 4), `app.models.{User,Profile}` (Task 2), `app.config.settings` (Task 1), `app.db.get_db` (Task 2).
- Produces: routes `GET /intake` (renders form), `POST /intake` (accepts `cv_file` (.txt only), `target_roles`, `target_locations`, `domains`, `seniority`, `tone` form fields; creates/updates the single `User`+`Profile`; redirects to `/contacts` with 303). Also produces `get_or_create_default_user(db) -> User`, reused by later tasks.

- [ ] **Step 1: Write the failing tests**

`tests/test_intake_route.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_intake_route.py -v`
Expected: FAIL (404 for unknown route / ModuleNotFoundError for `app.routes.intake`)

- [ ] **Step 3: Implement app/routes/__init__.py**

`app/routes/__init__.py`: (empty file)

- [ ] **Step 4: Implement app/routes/intake.py**

`app/routes/intake.py`:
```python
import json

import anthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.cv_parser import parse_cv
from app.db import get_db
from app.models import Profile, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).first()
    if user is None:
        user = User(email="local-user@contactcreator.local")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.get("/intake")
def show_intake_form(request: Request):
    return templates.TemplateResponse("intake.html", {"request": request})


@router.post("/intake")
async def submit_intake(
    cv_file: UploadFile = File(...),
    target_roles: str = Form(...),
    target_locations: str = Form(...),
    domains: str = Form(...),
    seniority: str = Form(...),
    tone: str = Form("professional"),
    db: Session = Depends(get_db),
):
    if not cv_file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=400, detail="Please upload a plain text (.txt) CV file for now."
        )

    cv_bytes = await cv_file.read()
    cv_text = cv_bytes.decode("utf-8", errors="ignore")

    questionnaire_answers = (
        f"Target roles: {target_roles}\n"
        f"Target locations: {target_locations}\n"
        f"Domains: {domains}\n"
        f"Seniority: {seniority}\n"
        f"Tone: {tone}"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    structured = parse_cv(
        cv_text=cv_text,
        questionnaire_answers=questionnaire_answers,
        client=client,
        model=settings.claude_model,
    )

    user = get_or_create_default_user(db)
    profile = db.query(Profile).filter_by(user_id=user.id).first()
    if profile is None:
        profile = Profile(user_id=user.id, cv_text=cv_text)
        db.add(profile)

    profile.cv_text = cv_text
    profile.skills = json.dumps(structured.skills)
    profile.years_experience = structured.years_experience
    profile.domains = json.dumps(structured.domains)
    profile.target_roles = json.dumps(structured.target_roles)
    profile.target_locations = json.dumps(structured.target_locations)
    profile.seniority = structured.seniority
    profile.tone = structured.tone
    db.commit()

    return RedirectResponse(url="/contacts", status_code=303)
```

- [ ] **Step 5: Implement app/templates/intake.html**

`app/templates/intake.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ContactCreator - Intake</title>
</head>
<body>
    <h1>Tell ContactCreator about you</h1>
    <form action="/intake" method="post" enctype="multipart/form-data">
        <label for="cv_file">CV (.txt file):</label><br>
        <input type="file" id="cv_file" name="cv_file" accept=".txt" required><br><br>

        <label for="target_roles">Target roles (comma-separated):</label><br>
        <input type="text" id="target_roles" name="target_roles" placeholder="Backend Engineer, AI Automation Engineer" required><br><br>

        <label for="target_locations">Target locations:</label><br>
        <input type="text" id="target_locations" name="target_locations" placeholder="Yerevan, EU remote" required><br><br>

        <label for="domains">Domain expertise:</label><br>
        <input type="text" id="domains" name="domains" placeholder="banking, call-center" required><br><br>

        <label for="seniority">Seniority:</label><br>
        <select id="seniority" name="seniority">
            <option value="junior">Junior</option>
            <option value="mid" selected>Mid</option>
            <option value="senior">Senior</option>
            <option value="lead">Lead</option>
        </select><br><br>

        <label for="tone">Outreach tone:</label><br>
        <select id="tone" name="tone">
            <option value="formal">Formal</option>
            <option value="professional" selected>Professional</option>
            <option value="casual">Casual</option>
        </select><br><br>

        <button type="submit">Save profile</button>
    </form>
</body>
</html>
```

- [ ] **Step 6: Register the router**

Modify `app/main.py` to:
```python
from fastapi import FastAPI

from app.db import engine
from app.models import Base
from app.routes.intake import router as intake_router

app = FastAPI(title="ContactCreator")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(intake_router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_intake_route.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests so far)

- [ ] **Step 9: Commit**

```bash
git add app/routes/__init__.py app/routes/intake.py app/templates/intake.html app/main.py tests/test_intake_route.py
git commit -m "feat: add CV intake route and form"
```

---

### Task 7: Discovery Route (Apollo Search + Credit Enforcement)

**Files:**
- Create: `app/routes/discovery.py`
- Create: `app/templates/contacts.html`
- Modify: `app/models.py`
- Modify: `app/main.py`
- Test: `tests/test_discovery_route.py`

**Interfaces:**
- Consumes: `app.apollo_client.{ApolloClient,SearchCriteria}` (Task 3), `app.credit_tracker.{CreditTracker,CreditLimitExceededError}` (Task 3), `app.models.{Company,Contact,User}` (Task 2), `app.routes.intake.get_or_create_default_user` is NOT reused here — this route reads the existing user via `db.query(User).first()` since intake must run first.
- Produces: `app.models.ApolloUsage(id, used, period_start)` (new model); routes `GET /contacts` (lists discovered contacts + remaining Apollo credits), `POST /contacts/discover` (runs an Apollo search from the profile's criteria, persists new `Company`/`Contact` rows, returns `{"discovered": int, "credits_remaining": int}`, or 400 if no profile exists yet, or 429 if out of credits).

- [ ] **Step 1: Add the ApolloUsage model**

Modify `app/models.py`: change the import line
```python
from sqlalchemy import Column, DateTime
```
to
```python
from sqlalchemy import Column, Date, DateTime
```
and add this class at the end of the file:
```python
class ApolloUsage(Base):
    __tablename__ = "apollo_usage"
    id = Column(Integer, primary_key=True)
    used = Column(Integer, default=0)
    period_start = Column(Date)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_discovery_route.py`:
```python
import json
from datetime import date
from unittest.mock import MagicMock, patch

from app.apollo_client import ApolloPerson
from app.models import Profile, User


def _create_profile(db):
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
    return user


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_creates_company_and_contact(mock_apollo_cls, client):
    from app.db import SessionLocal

    db = SessionLocal()
    _create_profile(db)
    db.close()

    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = [
        ApolloPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_apollo_cls.return_value = mock_apollo

    response = client.post("/contacts/discover")

    assert response.status_code == 200
    body = response.json()
    assert body["discovered"] == 1

    list_response = client.get("/contacts")
    assert "Jane Doe" in list_response.text
    assert "Example Bank" in list_response.text


def test_discover_contacts_requires_profile(client):
    response = client.post("/contacts/discover")
    assert response.status_code == 400


@patch("app.routes.discovery.ApolloClient")
def test_discover_contacts_blocks_when_out_of_credits(mock_apollo_cls, client):
    from app.db import SessionLocal
    from app.models import ApolloUsage

    db = SessionLocal()
    _create_profile(db)
    db.add(ApolloUsage(used=60, period_start=date.today()))
    db.commit()
    db.close()

    response = client.post("/contacts/discover")

    assert response.status_code == 429
    mock_apollo_cls.assert_not_called()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_discovery_route.py -v`
Expected: FAIL (404 for unknown routes / ModuleNotFoundError for `app.routes.discovery`)

- [ ] **Step 4: Implement app/routes/discovery.py**

`app/routes/discovery.py`:
```python
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.apollo_client import ApolloClient, SearchCriteria
from app.config import settings
from app.credit_tracker import CreditTracker
from app.db import get_db
from app.models import ApolloUsage, Company, Contact, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

RESULTS_PER_SEARCH = 25


def _load_usage(db: Session) -> ApolloUsage:
    usage = db.query(ApolloUsage).first()
    if usage is None:
        usage = ApolloUsage(used=0, period_start=date.today())
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


@router.get("/contacts")
def list_contacts(request: Request, db: Session = Depends(get_db)):
    contacts = db.query(Contact).all()
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.apollo_monthly_credit_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    return templates.TemplateResponse(
        "contacts.html",
        {
            "request": request,
            "contacts": contacts,
            "credits_remaining": tracker.remaining(),
            "credits_limit": tracker.limit,
        },
    )


@router.post("/contacts/discover")
def discover_contacts(db: Session = Depends(get_db)):
    user = db.query(User).first()
    if user is None or user.profile is None:
        raise HTTPException(status_code=400, detail="Complete intake first at /intake.")

    profile = user.profile
    usage = _load_usage(db)
    tracker = CreditTracker(
        limit=settings.apollo_monthly_credit_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    tracker.reset_if_new_period(today=date.today())

    if not tracker.can_spend(RESULTS_PER_SEARCH):
        raise HTTPException(
            status_code=429,
            detail=f"Out of Apollo credits until period resets. {tracker.remaining()} remaining.",
        )

    criteria = SearchCriteria(
        titles=json.loads(profile.target_roles),
        locations=json.loads(profile.target_locations),
        industries=json.loads(profile.domains),
        per_page=RESULTS_PER_SEARCH,
    )

    apollo_client = ApolloClient(api_key=settings.apollo_api_key)
    people = apollo_client.search_people(criteria)

    for person in people:
        company = None
        if person.company_domain:
            company = db.query(Company).filter_by(domain=person.company_domain).first()
        if company is None:
            company = Company(
                name=person.company_name or "Unknown",
                domain=person.company_domain,
                source="apollo",
            )
            db.add(company)
            db.commit()
            db.refresh(company)

        existing = None
        if person.email:
            existing = (
                db.query(Contact).filter_by(email=person.email, user_id=user.id).first()
            )
        if existing is None:
            db.add(
                Contact(
                    user_id=user.id,
                    company_id=company.id,
                    name=person.name,
                    title=person.title,
                    linkedin_url=person.linkedin_url,
                    email=person.email,
                    discovery_source="apollo",
                )
            )

    tracker.spend(RESULTS_PER_SEARCH)
    usage.used = tracker.used
    usage.period_start = tracker.period_start
    db.commit()

    return {"discovered": len(people), "credits_remaining": tracker.remaining()}
```

- [ ] **Step 5: Implement app/templates/contacts.html**

`app/templates/contacts.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ContactCreator - Contacts</title>
</head>
<body>
    <h1>Contacts</h1>
    <p>Apollo credits remaining this period: {{ credits_remaining }} / {{ credits_limit }}</p>
    <form action="/contacts/discover" method="post">
        <button type="submit">Find new contacts</button>
    </form>
    <table border="1" cellpadding="6">
        <thead>
            <tr>
                <th>Name</th>
                <th>Title</th>
                <th>Company</th>
                <th>LinkedIn</th>
                <th>Email</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for contact in contacts %}
            <tr>
                <td>{{ contact.name }}</td>
                <td>{{ contact.title }}</td>
                <td>{{ contact.company.name if contact.company else "" }}</td>
                <td><a href="{{ contact.linkedin_url }}">{{ contact.linkedin_url }}</a></td>
                <td>{{ contact.email }}</td>
                <td>
                    <form action="/outreach/generate/{{ contact.id }}" method="post">
                        <button type="submit">Generate drafts</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    <p><a href="/outreach">Go to outreach queue</a></p>
</body>
</html>
```

- [ ] **Step 6: Register the router**

Modify `app/main.py` to add the import and include line:
```python
from app.routes.discovery import router as discovery_router
```
and
```python
app.include_router(discovery_router)
```
(both added alongside the existing `intake_router` lines from Task 6).

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_discovery_route.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests so far)

- [ ] **Step 9: Commit**

```bash
git add app/routes/discovery.py app/templates/contacts.html app/models.py app/main.py tests/test_discovery_route.py
git commit -m "feat: add Apollo discovery route with credit enforcement"
```

---

### Task 8: Outreach Review Queue

**Files:**
- Create: `app/routes/outreach.py`
- Create: `app/templates/outreach.html`
- Modify: `app/main.py`
- Test: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.drafting.{draft_linkedin_note,draft_email}` (Task 5), `app.models.{Contact,OutreachChannel,OutreachMessage,OutreachStatus,User}` (Task 2/3), `app.config.settings` (Task 1).
- Produces: routes `POST /outreach/generate/{contact_id}` (generates and saves both a LinkedIn and email draft for a contact, returns `{"linkedin": str, "email": str}`, 404 if contact not found, 400 if the contact's user has no profile), `GET /outreach` (lists all `drafted`-status messages), `POST /outreach/{message_id}/mark-sent` (sets status to `sent`, `sent_at` to now, `follow_up_due_at` to now + 6 days, returns `{"status": "sent", "follow_up_due_at": str}`).

- [ ] **Step 1: Write the failing tests**

`tests/test_outreach_route.py`:
```python
import json
from unittest.mock import MagicMock, patch

from app.models import Company, Contact, Profile, User


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v`
Expected: FAIL (404 for unknown routes / ModuleNotFoundError for `app.routes.outreach`)

- [ ] **Step 3: Implement app/routes/outreach.py**

`app/routes/outreach.py`:
```python
import json
from datetime import datetime, timedelta

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.drafting import draft_email, draft_linkedin_note
from app.models import Contact, OutreachChannel, OutreachMessage, OutreachStatus, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _profile_summary(profile) -> str:
    skills = ", ".join(json.loads(profile.skills or "[]"))
    domains = ", ".join(json.loads(profile.domains or "[]"))
    return (
        f"{profile.years_experience} years of experience. "
        f"Skills: {skills}. Domain expertise: {domains}. Seniority: {profile.seniority}."
    )


@router.post("/outreach/generate/{contact_id}")
def generate_drafts(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter_by(id=contact_id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    user = db.query(User).filter_by(id=contact.user_id).first()
    if user is None or user.profile is None:
        raise HTTPException(status_code=400, detail="Complete intake first at /intake.")

    summary = _profile_summary(user.profile)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    company_name = contact.company.name if contact.company else "their company"

    linkedin_text = draft_linkedin_note(
        profile_summary=summary,
        contact_name=contact.name,
        contact_title=contact.title or "",
        company_name=company_name,
        client=client,
        model=settings.claude_model,
    )
    email_text = draft_email(
        profile_summary=summary,
        contact_name=contact.name,
        contact_title=contact.title or "",
        company_name=company_name,
        client=client,
        model=settings.claude_model,
    )

    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.linkedin,
            draft_text=linkedin_text,
            status=OutreachStatus.drafted,
        )
    )
    db.add(
        OutreachMessage(
            contact_id=contact.id,
            channel=OutreachChannel.email,
            draft_text=email_text,
            status=OutreachStatus.drafted,
        )
    )
    db.commit()

    return {"linkedin": linkedin_text, "email": email_text}


@router.get("/outreach")
def list_outreach(request: Request, db: Session = Depends(get_db)):
    messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.drafted).all()
    )
    return templates.TemplateResponse("outreach.html", {"request": request, "messages": messages})


@router.post("/outreach/{message_id}/mark-sent")
def mark_sent(message_id: int, db: Session = Depends(get_db)):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    message.follow_up_due_at = datetime.utcnow() + timedelta(days=6)
    db.commit()

    return {"status": "sent", "follow_up_due_at": message.follow_up_due_at.isoformat()}
```

- [ ] **Step 4: Implement app/templates/outreach.html**

`app/templates/outreach.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ContactCreator - Outreach Queue</title>
</head>
<body>
    <h1>Outreach Queue</h1>
    {% for message in messages %}
    <div style="border:1px solid #ccc; padding:10px; margin-bottom:10px;">
        <p><strong>{{ message.contact.name }}</strong> ({{ message.channel.value }}) &mdash; {{ message.contact.title }} at {{ message.contact.company.name if message.contact.company else "" }}</p>
        <textarea readonly rows="6" cols="60">{{ message.draft_text }}</textarea><br>
        <form action="/outreach/{{ message.id }}/mark-sent" method="post" style="display:inline;">
            <button type="submit">Mark as sent</button>
        </form>
    </div>
    {% endfor %}
    {% if not messages %}
    <p>No drafts waiting for review. Go to <a href="/contacts">Contacts</a> to discover people and generate drafts.</p>
    {% endif %}
</body>
</html>
```

- [ ] **Step 5: Register the router**

Modify `app/main.py` to add the import and include line:
```python
from app.routes.outreach import router as outreach_router
```
and
```python
app.include_router(outreach_router)
```
(both added alongside the existing `intake_router`/`discovery_router` lines).

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests in the project)

- [ ] **Step 8: Commit**

```bash
git add app/routes/outreach.py app/templates/outreach.html app/main.py tests/test_outreach_route.py
git commit -m "feat: add outreach review queue"
```

---

## Done Criteria for Milestone A

- [ ] `pytest -v` passes with zero failures.
- [ ] `docker compose up --build` starts the app and Postgres successfully.
- [ ] Manually visiting `/intake`, submitting a `.txt` CV + questionnaire, visiting `/contacts`, clicking "Find new contacts," clicking "Generate drafts" on a contact, and seeing the draft on `/outreach` all work end-to-end with real `ANTHROPIC_API_KEY` and `APOLLO_API_KEY` values in `.env`.
- [ ] Every task above is checked off and has a corresponding commit.
