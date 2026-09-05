# Milestone B: Tracking & Follow-up — Design

## Context

Milestone A (merged to `master`) built the core pipeline: CV intake, Hunter.io-based contact discovery, Claude-drafted LinkedIn/email outreach, and a manual "mark as sent" action. The original approved spec (`docs/superpowers/specs/2026-09-05-contact-creator-phase1-design.md`, section "5. Tracking & follow-up") calls for a daily view showing drafts awaiting review, follow-ups due, and a funnel count, plus manual status updates when someone replies. Milestone A explicitly deferred all of this — the `Event` table exists in the schema but nothing writes to it, `follow_up_due_at` is set on send but nothing surfaces it, and the only status transition available is `drafted → sent`.

This milestone closes that gap. It also fixes a known simplification from Milestone A: the follow-up window is currently hardcoded to 6 *calendar* days; the spec calls for 6 *business* days, configurable.

## Goals

- Extend the existing `/outreach` page (no new page) with: funnel counts (Contacted → Replied → Interview), a "Follow-ups due" section, and the existing "Drafts awaiting review" section.
- Add manual status-transition actions: `sent → replied`, `sent → no_response`, `replied → interview`, `replied → rejected` — enforced server-side, not just hidden in the UI.
- Wire the `Event` table into every status transition (including the existing `mark-sent` action, which currently logs nothing), so a timeline exists in the data even though no UI reads it yet.
- Switch the follow-up window from hardcoded 6 calendar days to a configurable number of *business* days (`FOLLOW_UP_BUSINESS_DAYS` env var, default 6).

## Non-goals

- No per-contact timeline UI — `Event` rows are written for future use, not displayed this milestone.
- No automated follow-up message drafting or reminders (e.g. no cron job, no email/notification when a follow-up is due) — the user sees it when they open `/outreach`.
- No changes to discovery, drafting, or intake — this milestone only touches the outreach/tracking surface.

## Data Model & Config

No schema changes — `OutreachMessage.status`, `OutreachMessage.follow_up_due_at`, and `Event(contact_id, type, note, timestamp)` already exist and support this milestone.

New setting in `app/config.py`: `follow_up_business_days: int`, read from `FOLLOW_UP_BUSINESS_DAYS` env var, default `6`.

**Status transitions**, enforced server-side:

| From | To | Trigger |
|---|---|---|
| `drafted` | `sent` | existing `mark-sent` action (unchanged behavior, now also logs an `Event`) |
| `sent` | `replied` | new status action |
| `sent` | `no_response` | new status action |
| `replied` | `interview` | new status action |
| `replied` | `rejected` | new status action |

Any other requested transition (e.g. `drafted → replied`, `sent → interview`) is rejected with `400`.

Every successful transition (including `mark-sent`) writes one `Event` row: `contact_id` (from the message's contact), `type` set to the new status value, `note` set to `f"{old_status} → {new_status}"`, `timestamp` set to now.

## Components

### `app/business_days.py` (new)

`business_days_from(start: date, business_days: int) -> date` — a pure function with no I/O. Walks forward one day at a time from `start`, counting only Monday–Friday, until `business_days` weekdays have been counted; returns that date. Fully unit-testable in isolation (e.g. a Friday start + 1 business day lands on the following Monday).

`app/routes/outreach.py`'s `mark_sent` uses this instead of `timedelta(days=6)`, passing `settings.follow_up_business_days`.

### `POST /outreach/{message_id}/status` (new route)

Form field: `status` (one of `replied`, `no_response`, `interview`, `rejected`). Looks up the `OutreachMessage` by id (404 if not found, matching the existing `mark-sent` pattern). Validates the requested transition against the table above based on the message's current status; `400` with a clear message if invalid or if `status` isn't one of the four recognized values. On success: updates `status`, writes the `Event`, commits, and returns `RedirectResponse("/outreach", status_code=303)` — consistent with every other mutating route in the app.

### `GET /outreach` (modified)

Adds two things to the existing template context:

- **Funnel counts**: three integer counts —
  - Contacted: messages with status in `{sent, replied, interview, rejected, no_response}` (i.e. everything that has been sent)
  - Replied: messages with status in `{replied, interview, rejected}`
  - Interview: messages with status `interview`
- **Follow-ups due**: messages with `status == 'sent'` and `follow_up_due_at <= now`, each rendered with its draft text (for reference) and "Mark Replied" / "Mark No Response" buttons.

The existing "Drafts awaiting review" section (status `drafted`) is unchanged. A "replied" message not yet resolved to `interview`/`rejected` is not specifically surfaced in a separate section in this milestone (it's reflected in the funnel counts; resolving it happens whenever the user next thinks about that contact — no dedicated queue for it, to avoid over-building beyond what the spec asks for).

## Testing

- **`app/business_days.py`**: unit tests covering — a run with no weekend in the window; starting the count on a Friday; a window spanning more than one weekend; 0 business days (returns `start` unchanged, edge case worth locking down explicitly).
- **`POST /outreach/{message_id}/status`**: one test per valid transition (asserts `status` changed and exactly one new `Event` row exists with the right `type`/`note`); one test per class of invalid transition (asserts `400`, no `Event` written, status unchanged); 404 for unknown message id; 400 for an unrecognized `status` value.
- **`GET /outreach`**: funnel counts render correctly for a fixture with messages in a mix of statuses; a message with `follow_up_due_at` in the future is absent from "Follow-ups due"; one with `follow_up_due_at` in the past is present.
- **`mark_sent`**: existing test updated to assert the new business-day math (rather than a flat 6-day delta) and to assert an `Event` row is now written.

## Error Handling

- Unknown `message_id` on the status route → `404`, matching `mark-sent`.
- Unrecognized `status` value → `400` with a message naming the valid values.
- Invalid transition for the message's current status (e.g. trying to mark a `drafted` message `replied`) → `400` with a message stating the message's current status and why the transition isn't allowed.
