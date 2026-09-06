# Milestone D: Hardening — Design

## Context

Milestones A, B, and C (merged to `master`) built the full Phase 1 pipeline: CV intake (`.txt` only), Hunter.io discovery, Claude-drafted outreach, tracking/follow-up, and real SMTP email sending. The milestone-A plan deferred four cleanup items to Milestone D: "broader test coverage, polished error handling, README/setup docs, and PDF CV support." This milestone closes those gaps. It is a hardening pass, not a new user-facing feature — no new pages, routes, or data model changes beyond what PDF support requires.

Auditing the current code turned up two concrete, previously-unhandled failure modes that the original spec's "never silently dropped" error-handling requirement (section "Error Handling," `docs/superpowers/specs/2026-09-05-contact-creator-phase1-design.md`) calls for but the codebase doesn't yet meet:

- `cv_parser.parse_cv` and `drafting.draft_*` only catch the case where Claude's response is empty or not valid JSON. A bad API key, rate limit, timeout, or network error raises the raw `anthropic` SDK exception straight through the route, producing a bare 500 with no user-visible message.
- `hunter_client.domain_search` calls `response.raise_for_status()` with nothing catching the resulting `httpx.HTTPStatusError`, and no handling of `httpx.RequestError` (timeout/connection failure) either — both propagate as an unhandled 500 through `POST /contacts/discover`.

`hunter_client.py` also has zero test coverage today (it replaced the original Apollo client mid-Milestone-A; the Apollo tests were never carried over).

## Goals

- Accept PDF CVs (`.pdf`) at `/intake` alongside the existing `.txt` support, extracting text via `pypdf`.
- Every external-API call (Anthropic, Hunter) that can fail for reasons other than "bad response content" (auth, rate limit, timeout, network) is caught and surfaced as the same kind of clean, visible error the app already gives for malformed-response failures — no code path produces a raw, unhandled 500 from a third-party SDK/HTTP exception.
- Close the test-coverage gaps this audit found: `hunter_client.py` (currently untested), the new PDF-extraction path, and the new error-handling paths.
- A root-level `README.md` covering what the tool is, setup, running it, and running tests.

## Non-goals

- No OAuth/Gmail-API CV or email changes — out of scope, unrelated to this milestone.
- No general-purpose global exception handler / custom error pages for FastAPI. The app's established error style is `HTTPException(status_code, detail=...)` returning JSON, used consistently by every route since Milestone A; this milestone extends *which* failures get caught into that style, not the style itself.
- No OCR or scanned-image PDF support. `pypdf` extracts embedded text only; a PDF with no extractable text layer is treated the same as any other unreadable upload (see Error Handling).
- No retry/backoff logic for transient API failures (e.g. auto-retrying a rate-limited Claude call). The existing pattern is "fail visibly, let the user retry manually" (e.g. drafting's existing 502 path) — this milestone applies that same pattern to the newly-caught failure modes, not a new resilience mechanism.
- No coverage-percentage target or tooling (e.g. `coverage.py` gating in CI) — "broader test coverage" here means closing the specific gaps identified above, not establishing a project-wide coverage threshold.

## Components

### PDF CV support

**`app/cv_parser.py` (modified):** new `CVExtractionError(Exception)`, and a new function `extract_pdf_text(pdf_bytes: bytes) -> str` that reads the PDF via `pypdf.PdfReader(io.BytesIO(pdf_bytes))`, concatenates `page.extract_text()` across all pages (skipping `None` returns from pages with no text layer), and raises `CVExtractionError("Could not extract any text from this PDF...")` if the concatenated result is empty/whitespace-only. A corrupt/unparseable file (`pypdf` raising on `PdfReader(...)` construction, e.g. `PdfReadError`) is also caught and re-raised as `CVExtractionError`.

**`app/routes/intake.py` (modified):** `submit_intake`'s upload-type check changes from "must end in `.txt`" to "must end in `.txt` or `.pdf`" (400 otherwise, same message pattern, listing both accepted types). Branch on extension: `.txt` keeps the current `cv_bytes.decode("utf-8", errors="ignore")` path; `.pdf` calls `extract_pdf_text(cv_bytes)` synchronously, before the existing `run_in_threadpool(parse_cv, ...)` call, wrapped in its own `try/except CVExtractionError` that returns a 400 with the error's message immediately (short-circuiting before any Claude call is made). This is a distinct branch from the existing `CVParseError` → 502 (400 because it's a bad upload, not a downstream service failure).

**`requirements.txt`:** add `pypdf` (pinned to a specific released version, matching the pinning style of every other dependency in the file).

### Error handling — Anthropic API failures

**`app/cv_parser.py` / `app/drafting.py` (modified):** wrap each `client.messages.create(...)` call in `try/except anthropic.APIError as e: raise CVParseError(...) from e` (respectively `DraftingError`) so that authentication errors, rate limits, connection errors, and timeouts — all subclasses of `anthropic.APIError` — are caught at the same boundary as the existing "empty content" / "invalid JSON" checks. No route-level changes needed: `intake.py`'s existing `except CVParseError` and `outreach.py`'s existing `except DraftingError` already turn these into the established 502 response.

### Error handling — Hunter API failures

**`app/hunter_client.py` (modified):** new `HunterAPIError(Exception)`. `domain_search` wraps its HTTP call and `raise_for_status()` in `try/except httpx.HTTPStatusError as e: raise HunterAPIError(f"Hunter.io returned an error: {e}") from e` and `except httpx.RequestError as e: raise HunterAPIError(f"Could not reach Hunter.io: {e}") from e`.

**`app/routes/discovery.py` (modified):** `discover_contacts` wraps the `hunter_client.domain_search(...)` call in `try/except HunterAPIError as e: raise HTTPException(status_code=502, detail=str(e))` — same 502-on-external-failure pattern already used by `intake.py` and `outreach.py`.

### README.md (new, repo root)

Sections: one-paragraph description of what ContactCreator does and who it's for (drawn from the Phase-1 spec's Context); setup (`cp .env.example .env`, fill in `ANTHROPIC_API_KEY`/`HUNTER_API_KEY`/SMTP vars, `docker compose up --build`); running tests (`pytest`, no Docker required, SQLite in-memory); a short usage walkthrough of the three pages in order (`/intake` → `/contacts` → `/outreach`) with one sentence each. This consolidates and supersedes the "How to Run Things" section currently living in `docs/superpowers/plans/2026-09-05-milestone-a-core-pipeline.md` (that section stays in the plan doc as historical record; the README is the new canonical copy for actually running the project).

## Testing

- **`tests/test_cv_parser.py`:** `extract_pdf_text` — happy path (mock `pypdf.PdfReader` returning pages with text), multi-page concatenation, a page returning `None` from `extract_text()` is skipped without error, empty-text-across-all-pages raises `CVExtractionError`, a construction-time `PdfReadError` raises `CVExtractionError`. Plus: `parse_cv` raising `anthropic.APIError` (e.g. mock `client.messages.create` to raise `anthropic.APIConnectionError`) is re-raised as `CVParseError`.
- **`tests/test_drafting.py`:** each of `draft_linkedin_note`/`draft_email`/`draft_email_subject` raising `anthropic.APIError` from the mocked client is re-raised as `DraftingError` (one representative test per function is sufficient given they share the exact same wrapping code path).
- **New `tests/test_hunter_client.py`:** `domain_search` happy path (mocked `httpx.Client.get` returning a realistic Hunter domain-search payload, asserting the returned `HunterPerson` list is built correctly, including the "no linkedin field" and "missing name falls back to email value" branches already present in `_to_hunter_person`); a mocked 401/429 response raising `httpx.HTTPStatusError` is re-raised as `HunterAPIError`; a mocked connection failure raising `httpx.RequestError` is re-raised as `HunterAPIError`.
- **`tests/test_discovery_route.py`:** new test that a `HunterAPIError` from a mocked `HunterClient.domain_search` results in a 502 with the error detail visible, and that no `Contact`/`Company` rows are created in that case.
- **`tests/test_intake_route.py`:** PDF upload happy path (mocked `extract_pdf_text` or a small real generated PDF fixture — implementer's choice, but must not require a real Claude call, consistent with every other intake test's mocking of `parse_cv`); PDF upload where extraction fails returns 400 with the `CVExtractionError` message; upload with an unsupported extension (e.g. `.docx`) still 400s with a message listing both accepted types.

All new tests follow the existing suite's conventions: no live network calls, mocking at the `httpx`/`anthropic` SDK boundary, run via plain `pytest` against SQLite in-memory.

## Error Handling

- Unreadable/unparseable PDF upload: 400, `CVExtractionError`'s message shown directly (e.g. "Could not extract any text from this PDF — it may be a scanned image with no text layer. Try exporting as .txt instead.").
- Unsupported file extension (not `.txt` or `.pdf`): unchanged 400 pattern, message updated to mention both accepted types.
- Claude API failure during CV parsing or drafting, for any reason (bad key, rate limit, timeout, network, malformed response): unchanged from the user's perspective — still a 502 via `CVParseError`/`DraftingError` — but now catches a strictly larger set of underlying causes than before.
- Hunter API failure during discovery, for any reason (bad key, rate limit, timeout, network, non-2xx response): 502 via the new `HunterAPIError`, mirroring the existing Claude-failure and SMTP-failure error styles. No contacts/companies are partially written when the call fails before returning data (the existing loop that creates them only runs after `domain_search` returns successfully).
