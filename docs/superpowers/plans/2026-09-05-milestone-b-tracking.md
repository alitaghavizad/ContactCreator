# Milestone B: Tracking & Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `/outreach` page with funnel counts and a follow-ups-due section, add server-enforced manual status transitions (sent→replied/no_response, replied→interview/rejected) that log to the `Event` table, and switch the follow-up window from hardcoded 6 calendar days to a configurable number of business days.

**Architecture:** No new routes beyond one (`POST /outreach/{message_id}/status`), no new pages, no schema changes. A new pure-function module (`app/business_days.py`) computes the follow-up date; `app/routes/outreach.py` gains an `Event`-logging helper reused by both the existing `mark-sent` action and the new status-transition action; `GET /outreach` gains two more queries and the template gains two more sections.

**Tech Stack:** Same as the rest of the project — FastAPI, SQLAlchemy, Jinja2, pytest. No new dependencies.

## Global Constraints

- No new pages — everything extends `GET /outreach` (per approved spec: `docs/superpowers/specs/2026-09-05-milestone-b-tracking-design.md`).
- Status transitions are enforced **server-side**: `sent→replied`, `sent→no_response`, `replied→interview`, `replied→rejected` are the only allowed transitions via the new endpoint; anything else is `400`.
- Every status transition (including the pre-existing `mark-sent`, which currently logs nothing) writes one `Event` row: `contact_id`, `type=<new status value>`, `note=f"{old_status.value} -> {new_status.value}"`, `timestamp=datetime.utcnow()`.
- Follow-up window: `FOLLOW_UP_BUSINESS_DAYS` env var, default `6`, read into `app.config.settings.follow_up_business_days`. Business days = Monday–Friday; weekends are skipped when counting forward from the send date.
- Funnel counts are counted at the **message** level (not deduplicated per contact) — this was an explicit call made in the design spec, not an oversight; a contact with both channels sent counts twice. Do not change this without checking with the human partner first.
- No timeline UI, no automated reminders/notifications, no changes to discovery/drafting/intake — out of scope for this plan.
- Every task ends with `pytest` passing before its commit.

**Plan addition beyond the literal spec text (documented here so a reviewer isn't surprised):** the design spec said a `replied` message not yet resolved to `interview`/`rejected` would not get "a dedicated queue... to avoid over-building." On reflection while writing this plan, that leaves the `replied→interview`/`replied→rejected` transitions in Global Constraints above completely unreachable from the UI — no page would ever show a button that POSTs them. Task 4 therefore adds one more small section to `/outreach`, "Replied — awaiting outcome," listing `replied`-status messages with Interview/Rejected buttons. This is the minimum addition needed for the already-approved status-transition feature to actually be usable — not a new page, not new business logic, just a third list in the same template using the same pattern as the other two sections.

---

### Task 1: Business-day follow-up calculation

**Files:**
- Create: `app/business_days.py`
- Test: `tests/test_business_days.py`

**Interfaces:**
- Produces: `app.business_days.business_days_from(start: date, business_days: int) -> date` — pure function, no I/O. Returns the date `business_days` weekdays (Mon–Fri) after `start`, skipping weekends. `business_days=0` returns `start` unchanged. `start` itself is never counted toward the total.

- [ ] **Step 1: Write the failing tests**

`tests/test_business_days.py`:
```python
from datetime import date

from app.business_days import business_days_from


def test_zero_business_days_returns_start_unchanged():
    # Wednesday, arbitrary day - no weekend involved.
    assert business_days_from(date(2024, 1, 3), 0) == date(2024, 1, 3)


def test_business_days_with_no_weekend_in_window():
    # Monday 2024-01-01 + 3 business days, all within the same working week.
    assert business_days_from(date(2024, 1, 1), 3) == date(2024, 1, 4)


def test_business_days_starting_on_friday_skips_weekend():
    # Friday 2024-01-05 + 1 business day -> Monday 2024-01-08.
    assert business_days_from(date(2024, 1, 5), 1) == date(2024, 1, 8)


def test_business_days_spans_one_weekend():
    # Monday 2024-01-01 + 6 business days -> Tuesday 2024-01-09
    # (Tue Wed Thu Fri, skip Sat/Sun, Mon Tue).
    assert business_days_from(date(2024, 1, 1), 6) == date(2024, 1, 9)


def test_business_days_spans_two_weekends():
    # Monday 2024-01-01 + 10 business days -> Monday 2024-01-15.
    assert business_days_from(date(2024, 1, 1), 10) == date(2024, 1, 15)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_business_days.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.business_days'`

- [ ] **Step 3: Implement app/business_days.py**

`app/business_days.py`:
```python
from datetime import date, timedelta


def business_days_from(start: date, business_days: int) -> date:
    """Return the date `business_days` weekdays (Mon-Fri) after `start`.

    Weekends are skipped when counting forward. `start` itself is never
    counted toward the total, and `business_days=0` returns `start`
    unchanged.
    """
    current = start
    counted = 0
    while counted < business_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 ... Sunday=6
            counted += 1
    return current
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_business_days.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add app/business_days.py tests/test_business_days.py
git commit -m "feat: add business-day follow-up date calculation"
```

---

### Task 2: Wire Event logging and business-day math into mark-sent

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `app/routes/outreach.py`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.business_days.business_days_from(start, business_days)` (Task 1).
- Produces: `app.config.settings.follow_up_business_days: int`; `app.routes.outreach._log_event(db: Session, contact_id: int, event_type: str, note: str) -> None` — writes one `Event` row and does not commit (caller commits). Task 3 reuses this exact function.

- [ ] **Step 1: Write the failing test**

Modify `tests/test_outreach_route.py`: replace the existing `test_mark_sent_updates_status_and_follow_up` test (currently asserting a flat 6-day delta) with this version, which asserts business-day math and an `Event` row:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outreach_route.py::test_mark_sent_updates_status_and_follow_up -v`
Expected: FAIL — `follow_up_due_at.date()` does not equal `expected_date` (still using the flat `timedelta(days=6)`), and no `Event` rows exist (`AttributeError` or assertion failure on `len(events) == 1`, since `settings.follow_up_business_days` doesn't exist yet either — this will actually fail earlier with `AttributeError: 'Settings' object has no attribute 'follow_up_business_days'`).

- [ ] **Step 3: Add the new setting**

Modify `app/config.py`: add this line inside the `Settings` class, after `hunter_monthly_search_limit`:
```python
    follow_up_business_days: int = int(os.environ.get("FOLLOW_UP_BUSINESS_DAYS", "6"))
```

- [ ] **Step 4: Add the new env var to the example file**

Modify `.env.example`, append:
```
FOLLOW_UP_BUSINESS_DAYS=6
```

- [ ] **Step 5: Implement the Event-logging helper and wire it + business-day math into mark_sent**

Modify `app/routes/outreach.py`:

Change the imports at the top of the file from:
```python
import json
from datetime import datetime, timedelta

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_linkedin_note
from app.models import Contact, OutreachChannel, OutreachMessage, OutreachStatus, User
```
to:
```python
import json
from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.business_days import business_days_from
from app.config import settings
from app.db import get_db
from app.drafting import DraftingError, draft_email, draft_linkedin_note
from app.models import Contact, Event, OutreachChannel, OutreachMessage, OutreachStatus, User
```

Add this helper function right after `_profile_summary` (before `generate_drafts`):
```python
def _log_event(db: Session, contact_id: int, event_type: str, note: str) -> None:
    db.add(Event(contact_id=contact_id, type=event_type, note=note, timestamp=datetime.utcnow()))
```

Replace the existing `mark_sent` function body:
```python
@router.post("/outreach/{message_id}/mark-sent")
def mark_sent(message_id: int, db: Session = Depends(get_db)):
    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    old_status = message.status
    message.status = OutreachStatus.sent
    message.sent_at = datetime.utcnow()
    follow_up_date = business_days_from(
        message.sent_at.date(), settings.follow_up_business_days
    )
    message.follow_up_due_at = datetime.combine(follow_up_date, message.sent_at.time())
    _log_event(
        db, message.contact_id, OutreachStatus.sent.value, f"{old_status.value} -> sent"
    )
    db.commit()

    # Browser form post: send the user back to the review queue.
    return RedirectResponse(url="/outreach", status_code=303)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_outreach_route.py::test_mark_sent_updates_status_and_follow_up -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add app/config.py .env.example app/routes/outreach.py tests/test_outreach_route.py
git commit -m "feat: log Event and use business-day math on mark-sent"
```

---

### Task 3: Status-transition endpoint

**Files:**
- Modify: `app/routes/outreach.py`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: `app.routes.outreach._log_event` (Task 2).
- Produces: route `POST /outreach/{message_id}/status` — form field `status` (one of `replied`, `no_response`, `interview`, `rejected`). 404 if message not found. 400 if `status` isn't one of those four values, or isn't a valid transition from the message's current status (`sent→{replied,no_response}`, `replied→{interview,rejected}` are the only valid transitions). On success: updates `status`, writes an `Event`, commits, redirects to `/outreach` (303).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outreach_route.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v -k update_status`
Expected: FAIL — 404s everywhere, since `POST /outreach/{message_id}/status` doesn't exist yet.

- [ ] **Step 3: Implement the endpoint**

Modify `app/routes/outreach.py`: change the `fastapi` import line from:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
```
to:
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request
```

Add this near the top of the file, after the router/templates setup, before `_profile_summary`:
```python
VALID_STATUS_VALUES = {"replied", "no_response", "interview", "rejected"}

VALID_TRANSITIONS = {
    OutreachStatus.sent: {OutreachStatus.replied, OutreachStatus.no_response},
    OutreachStatus.replied: {OutreachStatus.interview, OutreachStatus.rejected},
}
```

Add this new route, after `mark_sent`:
```python
@router.post("/outreach/{message_id}/status")
def update_status(message_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    if status not in VALID_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail="Status must be one of: replied, no_response, interview, rejected.",
        )

    message = db.query(OutreachMessage).filter_by(id=message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    new_status = OutreachStatus(status)
    old_status = message.status
    allowed = VALID_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from {old_status.value} to {new_status.value}.",
        )

    message.status = new_status
    _log_event(
        db, message.contact_id, new_status.value, f"{old_status.value} -> {new_status.value}"
    )
    db.commit()

    return RedirectResponse(url="/outreach", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v -k update_status`
Expected: PASS (7/7)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add app/routes/outreach.py tests/test_outreach_route.py
git commit -m "feat: add manual status-transition endpoint"
```

---

### Task 4: Funnel counts, follow-ups due, and replied-awaiting-outcome on /outreach

**Files:**
- Modify: `app/routes/outreach.py`
- Modify: `app/templates/outreach.html`
- Modify: `tests/test_outreach_route.py`

**Interfaces:**
- Consumes: nothing new from other tasks — this task only touches `list_outreach` and the template.
- Produces: `GET /outreach` template context gains `follow_ups_due` (list of `OutreachMessage`), `replied_awaiting_outcome` (list of `OutreachMessage`), `contacted_count`, `replied_count`, `interview_count` (ints). `messages` (drafted-status list) is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_outreach_route.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outreach_route.py -v -k "funnel or follow_ups_due or awaiting_outcome"`
Expected: FAIL — `Contacted: 3` etc. not present in the current page, "overdue one"/"not due yet" not rendered at all (no such section exists yet), no `/status` links present anywhere.

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

    return templates.TemplateResponse(
        "outreach.html",
        {
            "request": request,
            "messages": drafted_messages,
            "follow_ups_due": follow_ups_due,
            "replied_awaiting_outcome": replied_awaiting_outcome,
            "contacted_count": contacted_count,
            "replied_count": replied_count,
            "interview_count": interview_count,
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
    <h1>Outreach Queue</h1>

    <p>Contacted: {{ contacted_count }} &rarr; Replied: {{ replied_count }} &rarr; Interview: {{ interview_count }}</p>

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

    <h2>Drafts awaiting review</h2>
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_outreach_route.py -v -k "funnel or follow_ups_due or awaiting_outcome"`
Expected: PASS (3/3)

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add app/routes/outreach.py app/templates/outreach.html tests/test_outreach_route.py
git commit -m "feat: add funnel counts, follow-ups due, and replied sections to /outreach"
```

---

## Done Criteria for Milestone B

- [ ] `pytest -v` passes with zero failures.
- [ ] Manually verified against the live app (`docker compose up --build`): mark a message sent, confirm its follow-up date lands on a weekday and an `Event` row exists (check via `docker compose exec db psql ...`); wait (or manually edit `follow_up_due_at` in the DB) for it to become due and confirm it shows in "Follow-ups due"; mark it Replied, confirm it moves to "Replied — awaiting outcome"; mark it Interview, confirm the funnel counts update.
- [ ] Every task above is checked off and has a corresponding commit.
