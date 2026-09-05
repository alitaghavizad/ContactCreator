# Milestone C: Email Sending — Design

## Context

Milestones A and B (merged to `master`) built the core pipeline plus tracking/follow-up: CV intake, Hunter.io contact discovery, Claude-drafted outreach, a manual "mark as sent" action, and manual reply/interview/rejected status tracking with `Event` logging. Both milestones treated "sending" as purely a status flip — nothing has ever actually delivered an email. The original spec (`docs/superpowers/specs/2026-09-05-contact-creator-phase1-design.md`, section "4. Outreach") calls for real email sending via SMTP with a daily send cap enforced in code, and for failures to be surfaced (never silently dropped) via the `failed` status (already defined on `OutreachMessage.status` but unused until now).

This milestone implements that: real SMTP sending (via a Gmail app password, not OAuth — chosen for simplicity over Gmail API OAuth), a daily send cap, and failure/retry handling. LinkedIn stays exactly as it is — manual copy/paste, "mark as sent" only flips status — per the spec's hard requirement that no automation touches LinkedIn.

## Goals

- Real SMTP email sending for the `email` channel, via a Gmail app password.
- A distinct "Send Email" action (separate from LinkedIn's "Mark as sent"), so the two channels' very different levels of automation are visually distinct to the user.
- Claude generates a subject line for each email draft (previously body-only).
- A daily send cap (default 20/day, configurable), enforced before any send attempt — only successful sends count against it.
- Failed sends set `status=failed` with the error visible in the UI, plus a "Retry Send" action on the same message.
- `mark_sent` (the existing LinkedIn action) is hardened to reject email-channel messages, so email can never be "fake-sent" without actually going through SMTP.

## Non-goals

- No Gmail OAuth — SMTP with an app password only. OAuth can be added later without touching the SMTP-vs-OAuth choice's surrounding design (the `email_client` module is the seam).
- No automated inbox reading to detect replies — unchanged from Milestone B, still manual.
- No email templates/personalization settings beyond what Claude already generates per contact.
- No changes to LinkedIn behavior, discovery, intake, or the Milestone B tracking UI beyond what's needed to add the new "Failed sends" section and the "Send Email"/"No email on file" branch in "Drafts awaiting review."

## Data Model & Config

- **`OutreachMessage.subject`**: new `Text, nullable` column. Populated only for `email`-channel messages at draft time; `NULL` for `linkedin`.
- **`OutreachMessage.error_message`**: new `Text, nullable` column. Set on a failed send attempt; cleared (`NULL`) on a subsequent successful retry.
- **`EmailSendUsage`**: new table (`id`, `used`, `period_start`), structurally identical to `DiscoveryUsage` from Milestone A. Tracked via the existing generic `CreditTracker` class, called with `period_length_days=1` for a daily (not monthly) reset.
- **New settings** in `app/config.py`, read from env vars:
  - `SMTP_HOST` (no default — must be set)
  - `SMTP_PORT` (default `587`)
  - `SMTP_USERNAME` (no default — must be set; the Gmail address)
  - `SMTP_PASSWORD` (no default — must be set; the 16-character app password)
  - `SMTP_FROM_EMAIL` (defaults to `SMTP_USERNAME` if unset)
  - `DAILY_EMAIL_SEND_LIMIT` (default `20`, per spec)
- **Daily-cap accounting**: only a successful send increments `EmailSendUsage.used`. A failed attempt (bad credentials, SMTP connection error, etc.) does not consume quota — the cap protects sending *reputation* (volume of real sends), not attempt count.
- **`mark_sent` guard**: rejects (400) if the target message's `channel != OutreachChannel.linkedin`. This is the one behavioral change to existing Milestone A/B code — everything else in `mark_sent` (business-day math, `Event` logging) is unchanged for LinkedIn messages.

## Components

### `app/email_client.py` (new)

`SMTPEmailClient(host: str, port: int, username: str, password: str, from_email: str)` with `.send(to_address: str, subject: str, body: str) -> None`. Internally: connects via `smtplib.SMTP(host, port)`, `starttls()`, `login(username, password)`, sends via `send_message` (a standard `email.message.EmailMessage` with `From`/`To`/`Subject` headers and the body as plain text), then quits the connection. Any `smtplib`/`ssl`/`socket` exception is caught and re-raised as a new `EmailSendError(Exception)` carrying the original error's string as its message — the route never sees a raw `smtplib` traceback.

### `app/drafting.py` (modified)

New function `draft_email_subject(profile_summary, contact_name, contact_title, company_name, client, model) -> str` — a short, separate Claude call (own system prompt asking for a short, specific subject line, no quotes, no markdown), following the exact same defensive-content-block-extraction and `DraftingError`-on-empty-response pattern already used by `draft_linkedin_note`/`draft_email`. Not parsed out of the body — a dedicated call, avoiding fragile text-splitting.

### `app/routes/outreach.py` (modified)

- `generate_drafts`: after generating the existing LinkedIn note and email body, also calls `draft_email_subject` for the email message and stores it in the new `subject` column when constructing that `OutreachMessage`. If `draft_email_subject` raises `DraftingError`, the whole generation attempt fails the same way a `DraftingError` from the body draft already does today (502, nothing committed) — subject generation is not allowed to silently degrade to a missing subject.
- `mark_sent`: adds the channel guard described above, checked alongside (not instead of) the existing transition-table check.
- New route `POST /outreach/{message_id}/send-email`:
  1. 404 if message not found.
  2. 400 if `message.channel != OutreachChannel.email`.
  3. 400 if `message.status` not in `{drafted, failed}` (only those two states may be (re)sent).
  4. 400 if `message.contact.email` is empty/`None` ("This contact has no email address on file.") — defense in depth; the UI hides the button in this case, but the route enforces it too.
  5. Load/roll over `EmailSendUsage` via `CreditTracker(limit=settings.daily_email_send_limit, ..., period_length_days=1)`; if `not tracker.can_spend(1)`, 429 with a reset-time message (same pattern as Hunter's 429 in the discovery route).
  6. Attempt `SMTPEmailClient(...).send(contact.email, message.subject, message.draft_text)`.
     - **Success:** `status=sent`, `sent_at=now`, `follow_up_due_at` via the existing `business_days_from` helper (identical math to `mark_sent`), `error_message=None`, log an `Event` (`type="sent"`, `note="<old_status> -> sent"`), spend 1 from the tracker, persist the tracker's `used`/`period_start`, commit.
     - **Failure (`EmailSendError`):** `status=failed`, `error_message=str(the caught error)`, log an `Event` (`type="failed"`, `note="<old_status> -> failed: <error>"`), commit — the daily-cap tracker is **not** spent.
  7. Redirect to `/outreach` (303) either way — consistent with every other mutating route in the app.

### `GET /outreach` (modified)

New template sections and context, alongside the existing funnel counts / follow-ups-due / replied-awaiting-outcome / drafted sections:
- **Emails-sent-today counter**: `Emails sent today: {used} / {limit}`, next to the existing funnel-count line — same visual pattern as the Hunter search counter on `/contacts`.
- **"Drafts awaiting review"** (existing section, modified): for a `linkedin`-channel message, unchanged ("Mark as sent" button). For an `email`-channel message: if `contact.email` is set, show a "Send Email" button (posts to the new route) instead of "Mark as sent"; if not, show "No email on file" with no button.
- **"Failed sends"** (new section, same visual pattern as "Follow-ups due"): lists messages with `status == failed`, showing the draft text, the `error_message`, and a "Retry Send" button (posts to the same `send-email` route — retry and initial send are the same action, gated by the route's own `status in {drafted, failed}` check).

## Testing

- **`app/email_client.py`**: unit tests mock `smtplib.SMTP` (patch the class) and assert `starttls()`, `login(username, password)`, and the sent message's `From`/`To`/`Subject`/body are correct; a test where the mocked SMTP client raises on `login` (bad credentials) asserts `EmailSendError` is raised with the original error's text preserved. No real network connection in any test.
- **`draft_email_subject`**: same mocked-Anthropic-client pattern as existing drafting tests, including the empty-content-block `DraftingError` case.
- **`send-email` route**: success path (status/sent_at/follow_up_due_at/error_message/Event/cap-increment all verified via direct DB query); SMTP-failure path (status=failed, error_message set, Event logged, cap NOT incremented — verified by checking `EmailSendUsage.used` unchanged); wrong-channel 400; wrong-status 400 (e.g. already `sent`); no-contact-email 400; cap-exhausted 429 with `SMTPEmailClient` never constructed (mirroring the existing "never call the external service on a blocked action" pattern from Hunter's credit check); retry-after-failure succeeds and clears `error_message`.
- **`mark_sent`**: new test confirming a 400 when attempted on an `email`-channel message, and that existing LinkedIn behavior is unaffected.
- **Page tests**: drafted email message with a contact email renders "Send Email"; one without renders "No email on file"; a failed message renders its error text and "Retry Send"; the daily counter renders the correct `used`/`limit` values.
- **One lifecycle test** (matching Milestone B's precedent): generate → send-email (mocked SMTP success) → appears correctly in funnel counts and the daily counter → a second contact's send-email (mocked SMTP failure) → appears in "Failed sends" with its error → retry (mocked success) → moves out of "Failed sends", counter increments.

## Error Handling

- SMTP connection/auth/send errors are always caught inside `SMTPEmailClient.send`, never propagate as a raw exception past `EmailSendError` — the route always ends in a clean `failed`-status commit, never an unhandled 500.
- Missing SMTP config (`SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD` unset): `SMTPEmailClient` will fail on connection/login exactly like a bad-credentials failure, going through the same `EmailSendError` → `failed`-status path — no special-cased startup validation is added in this milestone (out of scope; a misconfigured deployment simply fails every send with a visible error, which is itself the "never silently dropped" behavior the spec asks for).
- Daily cap exhausted: 429 with a reset-time message, identical pattern to Hunter's 429, so the app's error-messaging style stays consistent across both external-service integrations.
