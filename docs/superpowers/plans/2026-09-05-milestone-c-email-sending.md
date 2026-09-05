# Milestone C: Email Sending Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real SMTP email sending (Gmail app password) with a daily send cap, a distinct "Send Email" action separate from LinkedIn's manual "Mark as sent", Claude-generated subject lines, and failed-send/retry handling — closing out the last piece of the original Phase 1 spec's outreach requirements.

**Architecture:** A new `app/email_client.py` (SMTP wrapper, mirrors the shape of `app/hunter_client.py`) is called from a new `POST /outreach/{message_id}/send-email` route in the existing `app/routes/outreach.py`. The daily cap reuses the existing generic `CreditTracker` class (already used for Hunter's monthly cap) with a 1-day period instead of 30. `mark_sent` gets one added guard so it can never be used to fake-send an email.

**Tech Stack:** Same as the rest of the project — FastAPI, SQLAlchemy, Jinja2, pytest, Python's built-in `smtplib`/`email` modules (no new dependency).

## Global Constraints

- SMTP with a Gmail app password only — no OAuth (approved spec decision, `docs/superpowers/specs/2026-09-05-milestone-c-email-sending-design.md`).
- LinkedIn is untouched: "Mark as sent" stays manual/status-only. It must now reject (400) any attempt to use it on an `email`-channel message.
- Email gets its own `POST /outreach/{message_id}/send-email` action, which performs a real SMTP send. This same route handles both the initial send (`drafted` status) and a retry after failure (`failed` status).
- Daily send cap: `DAILY_EMAIL_SEND_LIMIT` env var, default `20`. Only a **successful** send increments the counter — a failed attempt does not spend quota.
- A failed send sets `status=failed` and `error_message=<the error>` — never silently dropped, per the spec's explicit error-handling requirement. A message with no contact email on file never gets a working "Send Email" button in the UI, and the route enforces this server-side too.
- Every task ends with `pytest` passing before its commit.

---

### Task 1: SMTP email client

**Files:**
- Create: `app/email_client.py`
- Test: `tests/test_email_client.py`

**Interfaces:**
- Produces: `app.email_client.EmailSendError(Exception)`; `app.email_client.SMTPEmailClient(host: str, port: int, username: str, password: str, from_email: str)` with `.send(to_address: str, subject: str, body: str) -> None`. Raises `EmailSendError` (wrapping the original exception's string) on any SMTP failure; never lets a raw `smtplib` exception escape.

- [ ] **Step 1: Write the failing tests**

`tests/test_email_client.py`:
```python
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.email_client import EmailSendError, SMTPEmailClient


@patch("app.email_client.smtplib.SMTP")
def test_send_calls_starttls_login_and_send_message(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="app-password",
        from_email="me@gmail.com",
    )
    client.send("jane@example.com", "Hello", "Hi Jane, ...")

    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587)
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("me@gmail.com", "app-password")
    mock_smtp.send_message.assert_called_once()

    sent_message = mock_smtp.send_message.call_args[0][0]
    assert sent_message["From"] == "me@gmail.com"
    assert sent_message["To"] == "jane@example.com"
    assert sent_message["Subject"] == "Hello"
    assert sent_message.get_content().strip() == "Hi Jane, ..."


@patch("app.email_client.smtplib.SMTP")
def test_send_raises_email_send_error_on_login_failure(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="wrong-password",
        from_email="me@gmail.com",
    )

    with pytest.raises(EmailSendError):
        client.send("jane@example.com", "Hello", "Hi Jane, ...")


@patch("app.email_client.smtplib.SMTP")
def test_send_raises_email_send_error_on_connection_failure(mock_smtp_cls):
    mock_smtp_cls.side_effect = ConnectionRefusedError("connection refused")

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="app-password",
        from_email="me@gmail.com",
    )

    with pytest.raises(EmailSendError):
        client.send("jane@example.com", "Hello", "Hi Jane, ...")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_email_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.email_client'`

- [ ] **Step 3: Implement app/email_client.py**

`app/email_client.py`:
```python
import smtplib
from email.message import EmailMessage


class EmailSendError(Exception):
    """Raised when sending an email via SMTP fails for any reason."""

    pass


class SMTPEmailClient:
    def __init__(self, host: str, port: int, username: str, password: str, from_email: str):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email

    def send(self, to_address: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self._host, self._port) as smtp:
                smtp.starttls()
                smtp.login(self._username, self._password)
                smtp.send_message(message)
        except Exception as e:
            raise EmailSendError(str(e)) from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_email_client.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add app/email_client.py tests/test_email_client.py
git commit -m "feat: add SMTP email client"
```

---

### Task 2: Claude-generated email subject lines

**Files:**
- Modify: `app/models.py`
- Modify: `app/drafting.py`
- Modify: `app/routes/outreach.py`
- Modify: `tests/test_drafting.py`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.drafting._first_text_block`, `app.drafting.DraftingError` (already exist).
- Produces: `app.drafting.draft_email_subject(profile_summary: str, contact_name: str, contact_title: str, company_name: str, client: anthropic.Anthropic, model: str) -> str` — same signature shape as `draft_email`/`draft_linkedin_note`, raises `DraftingError` on an empty/text-less response. `OutreachMessage.subject: Text, nullable` and `OutreachMessage.error_message: Text, nullable` — new columns, both unused by `linkedin`-channel messages (`subject` is `None` for those).

- [ ] **Step 1: Write the failing tests for draft_email_subject**

Add to `tests/test_drafting.py` (reuses the existing `_text_block`, `_thinking_block`, `_mock_client`, `_mock_client_with_blocks` helpers already in this file):
```python
from app.drafting import draft_email_subject


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_drafting.py -v -k email_subject`
Expected: FAIL with `ImportError: cannot import name 'draft_email_subject' from 'app.drafting'`

- [ ] **Step 3: Implement draft_email_subject**

Modify `app/drafting.py`: add this constant right after `EMAIL_SYSTEM_PROMPT`:
```python
EMAIL_SUBJECT_SYSTEM_PROMPT = """You write short, specific subject lines for cold outreach \
emails from a job seeker reaching out to someone in their target industry. The subject should \
be under 80 characters, reference something concrete and specific (not generic phrases like \
"Quick question" or "Following up"), and read naturally as an email subject line. Return ONLY \
the subject line text, no quotes, no markdown."""
```

Add this function at the end of the file, after `draft_email`:
```python
def draft_email_subject(
    profile_summary: str,
    contact_name: str,
    contact_title: str,
    company_name: str,
    client: anthropic.Anthropic,
    model: str,
) -> str:
    message = client.messages.create(
        model=model,
        max_tokens=200,
        system=EMAIL_SUBJECT_SYSTEM_PROMPT,
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
    if not message.content:
        raise DraftingError("Claude returned an empty response with no content blocks")
    return _first_text_block(message).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_drafting.py -v -k email_subject`
Expected: PASS (3/3)

- [ ] **Step 5: Add the model columns**

Modify `app/models.py`: replace the `OutreachMessage` class with:
```python
class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    channel = Column(SAEnum(OutreachChannel), nullable=False)
    draft_text = Column(Text, nullable=False)
    subject = Column(Text, nullable=True)
    status = Column(SAEnum(OutreachStatus), default=OutreachStatus.drafted)
    sent_at = Column(DateTime, nullable=True)
    follow_up_due_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    contact = relationship("Contact")
```

- [ ] **Step 6: Write the failing test for generate_drafts storing a subject**

Modify `tests/test_outreach_route.py`: replace `test_generate_drafts_creates_two_messages` with:
```python
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
```

Also add a new test right after it:
```python
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
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v -k generate_drafts`
Expected: FAIL — `AttributeError` (no `subject` column yet used) or `ImportError` (`draft_email_subject` not imported in `app.routes.outreach` yet).

- [ ] **Step 8: Wire subject generation into generate_drafts**

Modify `app/routes/outreach.py`: change the import line
```python
from app.drafting import DraftingError, draft_email, draft_linkedin_note
```
to
```python
from app.drafting import DraftingError, draft_email, draft_email_subject, draft_linkedin_note
```

Replace the body of `generate_drafts` from the `try:` block onward:
```python
    try:
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
        email_subject = draft_email_subject(
            profile_summary=summary,
            contact_name=contact.name,
            contact_title=contact.title or "",
            company_name=company_name,
            client=client,
            model=settings.claude_model,
        )
    except DraftingError:
        raise HTTPException(
            status_code=502, detail="Could not generate outreach drafts. Please try again."
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
            subject=email_subject,
            status=OutreachStatus.drafted,
        )
    )
    db.commit()

    # Browser form post: send the user to the review queue rather than raw JSON.
    return RedirectResponse(url="/outreach", status_code=303)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v -k generate_drafts`
Expected: PASS

- [ ] **Step 10: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 11: Commit**

```bash
git add app/models.py app/drafting.py app/routes/outreach.py tests/test_drafting.py tests/test_outreach_route.py
git commit -m "feat: generate email subject lines and store them with drafts"
```

---

### Task 3: Send-email route with daily cap, and the mark-sent channel guard

**Files:**
- Modify: `app/models.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `app/routes/outreach.py`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.email_client.{SMTPEmailClient, EmailSendError}` (Task 1); `app.credit_tracker.CreditTracker` (existing, generic); `app.business_days.business_days_from`, `app.routes.outreach._log_event` (existing).
- Produces: `app.models.EmailSendUsage(id, used, period_start)` — same shape as `DiscoveryUsage`. Route `POST /outreach/{message_id}/send-email`: 404 unknown message; 400 if `channel != email`; 400 if `status not in {drafted, failed}`; 400 if the contact has no email; 429 if the daily cap is spent (`SMTPEmailClient` never constructed in that case); on success — `status=sent`, `sent_at`, `follow_up_due_at` (business-day math, same as `mark_sent`), `error_message=None`, one `Event` logged, daily-cap usage incremented, 303 to `/outreach`; on `EmailSendError` — `status=failed`, `error_message=str(error)`, one `Event` logged, daily-cap usage **unchanged**, 303 to `/outreach`. `mark_sent` now also 400s if `message.channel != OutreachChannel.linkedin`.

- [ ] **Step 1: Add the EmailSendUsage model**

Modify `app/models.py`: add this class at the end of the file, after `DiscoveryUsage`:
```python
class EmailSendUsage(Base):
    __tablename__ = "email_send_usage"
    id = Column(Integer, primary_key=True)
    used = Column(Integer, default=0)
    period_start = Column(Date)
```

- [ ] **Step 2: Add SMTP/daily-cap settings**

Modify `app/config.py`: add these lines inside the `Settings` class, after `follow_up_business_days`:
```python
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username: str = os.environ.get("SMTP_USERNAME", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from_email: str = os.environ.get("SMTP_FROM_EMAIL", "") or os.environ.get(
        "SMTP_USERNAME", ""
    )
    daily_email_send_limit: int = int(os.environ.get("DAILY_EMAIL_SEND_LIMIT", "20"))
```

Modify `.env.example`, append:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
DAILY_EMAIL_SEND_LIMIT=20
```

- [ ] **Step 3: Write the failing tests**

Modify `tests/test_outreach_route.py`: change the `_create_contact` helper's signature to accept an optional email override (keeps every existing call working unchanged, since the default matches the current hardcoded value):
```python
def _create_contact(db, email="jane@example.com"):
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
        email=email,
        discovery_source="apollo",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact
```

Add these tests to `tests/test_outreach_route.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v -k "send_email or mark_sent_rejects_email"`
Expected: FAIL (404s / `ImportError` for `SMTPEmailClient`/`EmailSendUsage` not yet used in `app.routes.outreach`, and the `Contact(email=None)` case may fail at the DB layer until `Contact.email` is confirmed nullable — it already is, per the existing model).

- [ ] **Step 5: Implement the send-email route and the mark_sent guard**

Modify `app/routes/outreach.py`: change the import lines at the top from:
```python
import json
from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.business_days import business_days_from
from app.config import settings
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_email_subject, draft_linkedin_note
from app.models import Contact, Event, OutreachChannel, OutreachMessage, OutreachStatus, User
```
to:
```python
import json
from datetime import date, datetime, timedelta

import anthropic
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.business_days import business_days_from
from app.config import settings
from app.credit_tracker import CreditTracker
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_email_subject, draft_linkedin_note
from app.email_client import EmailSendError, SMTPEmailClient
from app.models import (
    Contact,
    Event,
    EmailSendUsage,
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    User,
)
```

Add this constant near the top, after `VALID_TRANSITIONS`:
```python
EMAIL_DAILY_PERIOD_DAYS = 1
```

Add this helper function after `_log_event`:
```python
def _load_email_usage(db: Session) -> EmailSendUsage:
    usage = db.query(EmailSendUsage).first()
    if usage is None:
        usage = EmailSendUsage(used=0, period_start=date.today())
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage
```

Modify `mark_sent`: add the channel check right after the existing 404 check (before the `old_status = message.status` line):
```python
    if message.channel != OutreachChannel.linkedin:
        raise HTTPException(
            status_code=400,
            detail="Email messages must be sent via Send Email, not marked as sent manually.",
        )
```

Add this new route at the end of the file, after `update_status`:
```python
@router.post("/outreach/{message_id}/send-email")
def send_email(message_id: int, db: Session = Depends(get_db)):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.channel != OutreachChannel.email:
        raise HTTPException(
            status_code=400, detail="This action is only available for email messages."
        )

    if message.status not in {OutreachStatus.drafted, OutreachStatus.failed}:
        raise HTTPException(
            status_code=400, detail=f"Cannot send from status {message.status.value}."
        )

    if not message.contact.email:
        raise HTTPException(status_code=400, detail="This contact has no email address on file.")

    usage = _load_email_usage(db)
    tracker = CreditTracker(
        limit=settings.daily_email_send_limit,
        used=usage.used,
        period_start=usage.period_start,
    )
    tracker.reset_if_new_period(today=date.today(), period_length_days=EMAIL_DAILY_PERIOD_DAYS)

    if not tracker.can_spend(1):
        resets_on = tracker.period_start + timedelta(days=EMAIL_DAILY_PERIOD_DAYS)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily email send limit reached. "
                f"{tracker.remaining()} remaining. Resets on {resets_on}."
            ),
        )

    old_status = message.status
    email_client = SMTPEmailClient(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
    )

    try:
        email_client.send(message.contact.email, message.subject or "", message.draft_text)
    except EmailSendError as e:
        message.status = OutreachStatus.failed
        message.error_message = str(e)
        _log_event(
            db,
            message.contact_id,
            OutreachStatus.failed.value,
            f"{old_status.value} -> failed: {e}",
        )
        db.commit()
        return RedirectResponse(url="/outreach", status_code=303)

    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    follow_up_date = business_days_from(message.sent_at.date(), settings.follow_up_business_days)
    message.follow_up_due_at = datetime.combine(follow_up_date, message.sent_at.time())
    message.error_message = None
    _log_event(db, message.contact_id, OutreachStatus.sent.value, f"{old_status.value} -> sent")

    tracker.spend(1)
    usage.used = tracker.used
    usage.period_start = tracker.period_start

    db.commit()

    return RedirectResponse(url="/outreach", status_code=303)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v -k "send_email or mark_sent_rejects_email"`
Expected: PASS (8/8)

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/config.py .env.example app/routes/outreach.py tests/test_outreach_route.py
git commit -m "feat: add send-email route with daily cap and mark-sent channel guard"
```

---

### Task 4: Failed-sends section, Send Email button, and the daily counter on /outreach

**Files:**
- Modify: `app/routes/outreach.py`
- Modify: `app/templates/outreach.html`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.routes.outreach._load_email_usage`, `EMAIL_DAILY_PERIOD_DAYS` (Task 3).
- Produces: `GET /outreach` template context gains `failed_messages` (list of `OutreachMessage`), `emails_sent_today` (int), `daily_email_limit` (int). Existing context keys unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outreach_route.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v -k "send_email_button or no_email_note or failed_sends or daily_email_counter"`
Expected: FAIL — the "Failed sends" heading doesn't exist yet, no `send-email` form appears in "Drafts awaiting review", no daily counter text is rendered.

- [ ] **Step 3: Implement the query and context changes**

Modify `app/routes/outreach.py`: replace the `list_outreach` function with:
```python
@router.get("/outreach")
def list_outreach(request: Request, db: Session = Depends(get_db)):
    drafted_messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.drafted).all()
    )
    follow_ups_due = (
        db.query(OutreachMessage)
        .filter(
            OutreachMessage.status == OutreachStatus.sent,
            OutreachMessage.follow_up_due_at <= datetime.utcnow(),
        )
        .all()
    )
    replied_awaiting_outcome = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.replied).all()
    )
    failed_messages = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.failed).all()
    )

    contacted_statuses = [
        OutreachStatus.sent,
        OutreachStatus.replied,
        OutreachStatus.interview,
        OutreachStatus.rejected,
        OutreachStatus.no_response,
    ]
    replied_statuses = [OutreachStatus.replied, OutreachStatus.interview, OutreachStatus.rejected]

    contacted_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status.in_(contacted_statuses)).count()
    )
    replied_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status.in_(replied_statuses)).count()
    )
    interview_count = (
        db.query(OutreachMessage).filter(OutreachMessage.status == OutreachStatus.interview).count()
    )

    email_usage = _load_email_usage(db)
    email_tracker = CreditTracker(
        limit=settings.daily_email_send_limit,
        used=email_usage.used,
        period_start=email_usage.period_start,
    )
    email_tracker.reset_if_new_period(today=date.today(), period_length_days=EMAIL_DAILY_PERIOD_DAYS)
    if email_tracker.used != email_usage.used or email_tracker.period_start != email_usage.period_start:
        email_usage.used = email_tracker.used
        email_usage.period_start = email_tracker.period_start
        db.commit()

    return templates.TemplateResponse(
        "outreach.html",
        {
            "request": request,
            "messages": drafted_messages,
            "follow_ups_due": follow_ups_due,
            "replied_awaiting_outcome": replied_awaiting_outcome,
            "failed_messages": failed_messages,
            "contacted_count": contacted_count,
            "replied_count": replied_count,
            "interview_count": interview_count,
            "emails_sent_today": email_tracker.used,
            "daily_email_limit": email_tracker.limit,
        },
    )
```

- [ ] **Step 4: Update the template**

Replace the full contents of `app/templates/outreach.html` with:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ContactCreator - Outreach Queue</title>
</head>
<body>
    {% include "_nav.html" %}
    <h1>Outreach Queue</h1>

    <p>Contacted: {{ contacted_count }} &rarr; Replied: {{ replied_count }} &rarr; Interview: {{ interview_count }}</p>
    <p>Emails sent today: {{ emails_sent_today }} / {{ daily_email_limit }}</p>

    <h2>Follow-ups due</h2>
    {% for message in follow_ups_due %}
    <div style="border:1px solid #e0a000; padding:10px; margin-bottom:10px;">
        <p><strong>{{ message.contact.name }}</strong> ({{ message.channel.value }}) &mdash; {{ message.contact.title }} at {{ message.contact.company.name if message.contact.company else "" }}</p>
        <textarea readonly rows="6" cols="60">{{ message.draft_text }}</textarea><br>
        <form action="/outreach/{{ message.id }}/status" method="post" style="display:inline;">
            <input type="hidden" name="status" value="replied">
            <button type="submit">Mark Replied</button>
        </form>
        <form action="/outreach/{{ message.id }}/status" method="post" style="display:inline;">
            <input type="hidden" name="status" value="no_response">
            <button type="submit">Mark No Response</button>
        </form>
    </div>
    {% endfor %}
    {% if not follow_ups_due %}
    <p>No follow-ups due right now.</p>
    {% endif %}

    <h2>Replied &mdash; awaiting outcome</h2>
    {% for message in replied_awaiting_outcome %}
    <div style="border:1px solid #2080e0; padding:10px; margin-bottom:10px;">
        <p><strong>{{ message.contact.name }}</strong> ({{ message.channel.value }}) &mdash; {{ message.contact.title }} at {{ message.contact.company.name if message.contact.company else "" }}</p>
        <form action="/outreach/{{ message.id }}/status" method="post" style="display:inline;">
            <input type="hidden" name="status" value="interview">
            <button type="submit">Mark Interview</button>
        </form>
        <form action="/outreach/{{ message.id }}/status" method="post" style="display:inline;">
            <input type="hidden" name="status" value="rejected">
            <button type="submit">Mark Rejected</button>
        </form>
    </div>
    {% endfor %}
    {% if not replied_awaiting_outcome %}
    <p>No replies awaiting an outcome.</p>
    {% endif %}

    <h2>Failed sends</h2>
    {% for message in failed_messages %}
    <div style="border:1px solid #d02020; padding:10px; margin-bottom:10px;">
        <p><strong>{{ message.contact.name }}</strong> ({{ message.channel.value }}) &mdash; {{ message.contact.title }} at {{ message.contact.company.name if message.contact.company else "" }}</p>
        <p style="color:#d02020;">Error: {{ message.error_message }}</p>
        <textarea readonly rows="6" cols="60">{{ message.draft_text }}</textarea><br>
        <form action="/outreach/{{ message.id }}/send-email" method="post" style="display:inline;">
            <button type="submit">Retry Send</button>
        </form>
    </div>
    {% endfor %}
    {% if not failed_messages %}
    <p>No failed sends.</p>
    {% endif %}

    <h2>Drafts awaiting review</h2>
    {% for message in messages %}
    <div style="border:1px solid #ccc; padding:10px; margin-bottom:10px;">
        <p><strong>{{ message.contact.name }}</strong> ({{ message.channel.value }}) &mdash; {{ message.contact.title }} at {{ message.contact.company.name if message.contact.company else "" }}</p>
        {% if message.channel.value == "email" and message.subject %}
        <p>Subject: {{ message.subject }}</p>
        {% endif %}
        <textarea readonly rows="6" cols="60">{{ message.draft_text }}</textarea><br>
        {% if message.channel.value == "linkedin" %}
        <form action="/outreach/{{ message.id }}/mark-sent" method="post" style="display:inline;">
            <button type="submit">Mark as sent</button>
        </form>
        {% elif message.contact.email %}
        <form action="/outreach/{{ message.id }}/send-email" method="post" style="display:inline;">
            <button type="submit">Send Email</button>
        </form>
        {% else %}
        <p>No email on file.</p>
        {% endif %}
    </div>
    {% endfor %}
    {% if not messages %}
    <p>No drafts waiting for review. Go to <a href="/contacts">Contacts</a> to discover people and generate drafts.</p>
    {% endif %}
</body>
</html>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v -k "send_email_button or no_email_note or failed_sends or daily_email_counter"`
Expected: PASS (4/4)

- [ ] **Step 6: Write and run the full-lifecycle test**

Add to `tests/test_outreach_route.py`:
```python
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
```

Run: `pytest tests/test_outreach_route.py -v -k test_full_email_lifecycle`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add app/routes/outreach.py app/templates/outreach.html tests/test_outreach_route.py
git commit -m "feat: add failed-sends section, Send Email button, and daily counter to /outreach"
```

---

## Done Criteria for Milestone C

- [ ] `pytest -v` passes with zero failures.
- [ ] Manually verified against the live app (`docker compose up --build`, with real `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD` — a real Gmail app password — set in `.env`): generate drafts for a contact with a real email address, click "Send Email," confirm a real email arrives; deliberately break the app password, click "Send Email" on a fresh draft, confirm it shows up in "Failed sends" with a real error message, fix the password, click "Retry Send," confirm it succeeds.
- [ ] Every task above is checked off and has a corresponding commit.
