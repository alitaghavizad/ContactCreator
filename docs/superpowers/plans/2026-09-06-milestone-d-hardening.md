# Milestone D: Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four gaps Milestone A deferred to Milestone D: PDF CV support, catching Anthropic/Hunter API failures that currently escape as unhandled 500s, closing `hunter_client.py`'s test-coverage gap, and a root-level README.

**Architecture:** No new routes, pages, or data model changes. All work modifies existing modules (`cv_parser.py`, `drafting.py`, `hunter_client.py`, `routes/intake.py`, `routes/discovery.py`) plus one new dependency (`pypdf`) and one new file (`README.md`).

**Tech Stack:** Same as existing app — Python 3.11, FastAPI, `anthropic` SDK, `httpx`, pytest. New: `pypdf==6.17.0`.

## Global Constraints

- Tests never call live Anthropic, Hunter, or SMTP APIs — mock at the SDK/`httpx` boundary, per the existing suite's convention (see `docs/superpowers/specs/2026-09-05-contact-creator-phase1-design.md`, "Testing Strategy").
- Every task ends with `pytest` passing before its commit.
- The app's established error style is `HTTPException(status_code, detail=<message>)` returning JSON — every new error path follows this, no new response format is introduced.
- No OCR, no scanned-PDF support — `pypdf` extracts embedded text only, per `docs/superpowers/specs/2026-09-06-milestone-d-hardening-design.md` ("Non-goals").
- No retry/backoff logic — the existing pattern is "fail visibly with a clear message, let the user retry manually."

---

### Task 1: PDF text extraction

**Files:**
- Modify: `requirements.txt`
- Modify: `app/cv_parser.py`
- Test: `tests/test_cv_parser.py`

**Interfaces:**
- Produces: `app.cv_parser.CVExtractionError` (Exception subclass); `app.cv_parser.extract_pdf_text(pdf_bytes: bytes) -> str`, raises `CVExtractionError` if the PDF is unreadable or has no extractable text.

- [ ] **Step 1: Add `pypdf` to `requirements.txt`**

Append to `requirements.txt`:
```
pypdf==6.17.0
```

Install it into the project's virtualenv:
```bash
.venv/Scripts/pip.exe install pypdf==6.17.0
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cv_parser.py` (add these imports alongside the existing ones at the top of the file):

```python
import io

from app.cv_parser import CVExtractionError, extract_pdf_text
```

Add these test functions at the end of the file. The first three mock `PdfReader` directly (matching how `test_hunter_client.py` and the Anthropic-mocking tests elsewhere in this suite avoid touching the real external/parsing library); the last one uses real garbage bytes against the real `pypdf.PdfReader` to verify the corrupt-file path end-to-end:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_cv_parser.py -v -k extract_pdf
```
Expected: FAIL with `ImportError` / `AttributeError` (`CVExtractionError` and `extract_pdf_text` don't exist yet).

- [ ] **Step 4: Implement `extract_pdf_text`**

In `app/cv_parser.py`, add imports at the top of the file (alongside the existing `import json`, `from dataclasses import ...`, `import anthropic`):

```python
import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError
```

Add, right after the `CVParseError` class definition:

```python
class CVExtractionError(Exception):
    """Raised when text cannot be extracted from an uploaded CV file."""
    pass


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_texts = [page.extract_text() for page in reader.pages]
    except PdfReadError as e:
        raise CVExtractionError(
            "Could not read this PDF - it may be corrupted. Try exporting as .txt instead."
        ) from e

    text = "\n".join(t for t in page_texts if t)
    if not text.strip():
        raise CVExtractionError(
            "Could not extract any text from this PDF - it may be a scanned image with "
            "no text layer. Try exporting as .txt instead."
        )
    return text
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_cv_parser.py -v
```
Expected: all PASS (existing tests plus the four new ones).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/cv_parser.py tests/test_cv_parser.py
git commit -m "feat: add PDF text extraction for CV uploads"
```

---

### Task 2: Accept PDF uploads at /intake

**Files:**
- Modify: `app/routes/intake.py`
- Test: `tests/test_intake_route.py`

**Interfaces:**
- Consumes: `app.cv_parser.CVExtractionError`, `app.cv_parser.extract_pdf_text` (from Task 1).
- Produces: no new interfaces — `POST /intake` now accepts `.pdf` in addition to `.txt`.

- [ ] **Step 1: Update the existing rejection test and add PDF tests**

In `tests/test_intake_route.py`, replace `test_submit_intake_rejects_non_txt_file`:

```python
def test_submit_intake_rejects_unsupported_file_extension(client):
    cv_file = io.BytesIO(b"some binary content")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan",
            "domains": "banking",
            "seniority": "mid",
        },
        files={"cv_file": ("cv.docx", cv_file, "application/vnd.openxmlformats")},
    )

    assert response.status_code == 400
    assert ".txt" in response.json()["detail"]
    assert ".pdf" in response.json()["detail"]
```

Add these new tests at the end of the file:

```python
@patch("app.routes.intake.extract_pdf_text")
@patch("app.routes.intake.anthropic.Anthropic")
def test_submit_intake_accepts_pdf_file(mock_anthropic_cls, mock_extract_pdf_text, client):
    mock_extract_pdf_text.return_value = "5 years Java developer with banking domain experience."
    _mock_claude_response(
        mock_anthropic_cls,
        '{"skills": ["Java"], "years_experience": 5, "domains": ["banking"], '
        '"target_roles": ["Backend Engineer"], "target_locations": ["Yerevan"], '
        '"seniority": "mid", "tone": "professional"}',
    )

    cv_file = io.BytesIO(b"%PDF-1.4 fake but well-formed-enough pdf bytes")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan",
            "domains": "banking",
            "seniority": "mid",
        },
        files={"cv_file": ("cv.pdf", cv_file, "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    mock_extract_pdf_text.assert_called_once()

    db = SessionLocal()
    try:
        profile = db.query(Profile).first()
        assert profile.cv_text == "5 years Java developer with banking domain experience."
    finally:
        db.close()


@patch("app.routes.intake.extract_pdf_text")
def test_submit_intake_handles_unreadable_pdf(mock_extract_pdf_text, client):
    from app.cv_parser import CVExtractionError

    mock_extract_pdf_text.side_effect = CVExtractionError(
        "Could not extract any text from this PDF."
    )

    cv_file = io.BytesIO(b"%PDF-1.4 scanned image pdf")

    response = client.post(
        "/intake",
        data={
            "target_roles": "Backend Engineer",
            "target_locations": "Yerevan",
            "domains": "banking",
            "seniority": "mid",
        },
        files={"cv_file": ("cv.pdf", cv_file, "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Could not extract any text" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_intake_route.py -v
```
Expected: `test_submit_intake_rejects_unsupported_file_extension` FAILs (a `.docx` file is currently rejected with the *old* message, which doesn't mention `.pdf`); the two new PDF tests FAIL (`.pdf` currently rejected outright, and `app.routes.intake.extract_pdf_text` doesn't exist to patch).

- [ ] **Step 3: Implement PDF support in the intake route**

In `app/routes/intake.py`, update the import line:

```python
from app.cv_parser import CVExtractionError, CVParseError, extract_pdf_text, parse_cv
```

Replace the file-extension check and text-decoding block inside `submit_intake`:

```python
    filename = cv_file.filename.lower()
    if not (filename.endswith(".txt") or filename.endswith(".pdf")):
        raise HTTPException(
            status_code=400,
            detail="Please upload a plain text (.txt) or PDF (.pdf) CV file.",
        )

    cv_bytes = await cv_file.read()
    if filename.endswith(".pdf"):
        try:
            cv_text = extract_pdf_text(cv_bytes)
        except CVExtractionError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        cv_text = cv_bytes.decode("utf-8", errors="ignore")
```

This replaces the old:
```python
    if not cv_file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=400, detail="Please upload a plain text (.txt) CV file for now."
        )

    cv_bytes = await cv_file.read()
    cv_text = cv_bytes.decode("utf-8", errors="ignore")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_intake_route.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: all PASS (no regressions elsewhere).

- [ ] **Step 6: Commit**

```bash
git add app/routes/intake.py tests/test_intake_route.py
git commit -m "feat: accept PDF CV uploads at /intake"
```

---

### Task 3: Catch Anthropic API failures in CV parsing and drafting

**Files:**
- Modify: `app/cv_parser.py`
- Modify: `app/drafting.py`
- Test: `tests/test_cv_parser.py`
- Test: `tests/test_drafting.py`

**Interfaces:**
- No new interfaces. `parse_cv` and `draft_linkedin_note`/`draft_email`/`draft_email_subject` now also raise `CVParseError`/`DraftingError` (already-existing exception types) when the underlying Anthropic SDK call raises `anthropic.APIError` (covers auth errors, rate limits, connection errors, timeouts).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cv_parser.py` (add `import httpx` and `import anthropic` to the top of the file alongside the existing imports):

```python
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
```

Add to `tests/test_drafting.py` (add `import httpx` and `import anthropic` to the top of the file alongside the existing imports):

```python
def test_draft_linkedin_note_raises_drafting_error_on_anthropic_api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(DraftingError):
        draft_linkedin_note(
            profile_summary="summary",
            contact_name="Jane",
            contact_title="Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )


def test_draft_email_raises_drafting_error_on_anthropic_api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(DraftingError):
        draft_email(
            profile_summary="summary",
            contact_name="Jane",
            contact_title="Manager",
            company_name="Example Bank",
            client=mock_client,
            model="claude-sonnet-5",
        )


def test_draft_email_subject_raises_drafting_error_on_anthropic_api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

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

```bash
.venv/Scripts/python.exe -m pytest tests/test_cv_parser.py tests/test_drafting.py -v -k anthropic_api_error
```
Expected: FAIL — `anthropic.APIConnectionError` currently propagates unmodified out of `parse_cv`/`draft_*`, so `pytest.raises(CVParseError)` / `pytest.raises(DraftingError)` does not match.

- [ ] **Step 3: Wrap the Anthropic call in `parse_cv`**

In `app/cv_parser.py`, replace:

```python
def parse_cv(
    cv_text: str,
    questionnaire_answers: str,
    client: anthropic.Anthropic,
    model: str,
) -> StructuredProfile:
    message = client.messages.create(
        model=model,
        max_tokens=2048,
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
```

with:

```python
def parse_cv(
    cv_text: str,
    questionnaire_answers: str,
    client: anthropic.Anthropic,
    model: str,
) -> StructuredProfile:
    try:
        message = client.messages.create(
            model=model,
            max_tokens=2048,
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
    except anthropic.APIError as e:
        raise CVParseError(f"Claude API request failed: {e}") from e
```

(The rest of the function — `raw_text = _first_text_block(message)` onward — is unchanged.)

- [ ] **Step 4: Wrap the Anthropic call in each `drafting.py` function**

In `app/drafting.py`, apply the same wrapping to all three functions. For `draft_linkedin_note`, replace:

```python
    system = LINKEDIN_SYSTEM_PROMPT.format(limit=LINKEDIN_CHAR_LIMIT)
    message = client.messages.create(
        model=model,
        max_tokens=500,
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
```

with:

```python
    system = LINKEDIN_SYSTEM_PROMPT.format(limit=LINKEDIN_CHAR_LIMIT)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=500,
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
    except anthropic.APIError as e:
        raise DraftingError(f"Claude API request failed: {e}") from e
```

For `draft_email`, replace:

```python
    message = client.messages.create(
        model=model,
        max_tokens=1200,
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
```

with:

```python
    try:
        message = client.messages.create(
            model=model,
            max_tokens=1200,
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
    except anthropic.APIError as e:
        raise DraftingError(f"Claude API request failed: {e}") from e
```

For `draft_email_subject`, replace:

```python
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
```

with:

```python
    try:
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
    except anthropic.APIError as e:
        raise DraftingError(f"Claude API request failed: {e}") from e
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_cv_parser.py tests/test_drafting.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/cv_parser.py app/drafting.py tests/test_cv_parser.py tests/test_drafting.py
git commit -m "fix: catch Anthropic API failures in CV parsing and drafting"
```

---

### Task 4: Catch Hunter API failures in discovery

**Files:**
- Create: `tests/test_hunter_client.py`
- Modify: `app/hunter_client.py`
- Modify: `app/routes/discovery.py`
- Test: `tests/test_discovery_route.py`

**Interfaces:**
- Produces: `app.hunter_client.HunterAPIError` (Exception subclass), raised by `HunterClient.domain_search` when the Hunter.io call fails for any reason (bad response status, network error).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hunter_client.py`:

```python
from unittest.mock import MagicMock

import httpx
import pytest

from app.hunter_client import HunterAPIError, HunterClient, HunterPerson


def _mock_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hunter.io/v2/domain-search")
    return httpx.Response(status_code, json=json_data, request=request)


def test_domain_search_returns_people():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {
            "data": {
                "organization": "Example Bank",
                "emails": [
                    {
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "position": "Engineering Manager",
                        "linkedin": "https://linkedin.com/in/janedoe",
                        "value": "jane@example.com",
                    }
                ],
            }
        }
    )
    client = HunterClient(api_key="test-key", http_client=mock_http)

    people = client.domain_search("example.com", limit=10)

    assert people == [
        HunterPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_http.get.assert_called_once_with(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": "example.com", "api_key": "test-key", "limit": 10, "type": "personal"},
    )


def test_domain_search_missing_name_falls_back_to_email_value():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"data": {"organization": None, "emails": [{"value": "person@example.com"}]}}
    )
    client = HunterClient(api_key="test-key", http_client=mock_http)

    people = client.domain_search("example.com")

    assert people[0].name == "person@example.com"
    assert people[0].linkedin_url is None
    assert people[0].title is None


def test_domain_search_raises_hunter_api_error_on_http_status_error():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"errors": [{"details": "invalid api key"}]}, status_code=401
    )
    client = HunterClient(api_key="bad-key", http_client=mock_http)

    with pytest.raises(HunterAPIError):
        client.domain_search("example.com")


def test_domain_search_raises_hunter_api_error_on_request_error():
    mock_http = MagicMock()
    mock_http.get.side_effect = httpx.ConnectError("connection refused")
    client = HunterClient(api_key="test-key", http_client=mock_http)

    with pytest.raises(HunterAPIError):
        client.domain_search("example.com")
```

Add to `tests/test_discovery_route.py` (add `from app.hunter_client import HunterAPIError` to the existing import line):

```python
@patch("app.routes.discovery.HunterClient")
def test_discover_contacts_returns_502_on_hunter_api_error(mock_hunter_cls, client):
    from app.db import SessionLocal
    from app.models import Company, Contact

    mock_hunter = MagicMock()
    mock_hunter.domain_search.side_effect = HunterAPIError("Hunter.io returned an error: 401")
    mock_hunter_cls.return_value = mock_hunter

    response = client.post(
        "/contacts/discover", data={"domain": "example.com"}, follow_redirects=False
    )

    assert response.status_code == 502
    assert "Hunter.io" in response.json()["detail"]

    db = SessionLocal()
    assert db.query(Company).count() == 0
    assert db.query(Contact).count() == 0
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_hunter_client.py tests/test_discovery_route.py -v
```
Expected: `tests/test_hunter_client.py` FAILs with `ImportError` (`HunterAPIError` doesn't exist yet); `test_discover_contacts_returns_502_on_hunter_api_error` FAILs (the route currently lets the exception propagate as an unhandled 500, not a 502).

- [ ] **Step 3: Add `HunterAPIError` and wrap the HTTP call**

In `app/hunter_client.py`, replace:

```python
from dataclasses import dataclass
from typing import Optional

import httpx

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
```

with:

```python
from dataclasses import dataclass
from typing import Optional

import httpx

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"


class HunterAPIError(Exception):
    """Raised when a Hunter.io API call fails, whether from a bad response or a network error."""
    pass
```

Then replace the body of `domain_search`:

```python
    def domain_search(self, domain: str, limit: int = 25) -> list[HunterPerson]:
        response = self._http.get(
            HUNTER_DOMAIN_SEARCH_URL,
            params={
                "domain": domain,
                "api_key": self._api_key,
                "limit": limit,
                "type": "personal",
            },
        )
        response.raise_for_status()
        data = response.json()
```

with:

```python
    def domain_search(self, domain: str, limit: int = 25) -> list[HunterPerson]:
        try:
            response = self._http.get(
                HUNTER_DOMAIN_SEARCH_URL,
                params={
                    "domain": domain,
                    "api_key": self._api_key,
                    "limit": limit,
                    "type": "personal",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HunterAPIError(f"Hunter.io returned an error: {e}") from e
        except httpx.RequestError as e:
            raise HunterAPIError(f"Could not reach Hunter.io: {e}") from e
        data = response.json()
```

(The rest of the function — building the `HunterPerson` list from `data` — is unchanged.)

- [ ] **Step 4: Catch `HunterAPIError` in the discovery route**

In `app/routes/discovery.py`, update the import line:

```python
from app.hunter_client import HunterAPIError, HunterClient
```

Replace:

```python
    hunter_client = HunterClient(api_key=settings.hunter_api_key)
    people = hunter_client.domain_search(domain, limit=RESULTS_PER_SEARCH)
```

with:

```python
    hunter_client = HunterClient(api_key=settings.hunter_api_key)
    try:
        people = hunter_client.domain_search(domain, limit=RESULTS_PER_SEARCH)
    except HunterAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_hunter_client.py tests/test_discovery_route.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/hunter_client.py app/routes/discovery.py tests/test_hunter_client.py tests/test_discovery_route.py
git commit -m "fix: catch Hunter.io API failures in discovery; add hunter_client tests"
```

---

### Task 5: README.md

**Files:**
- Create: `README.md`

**Interfaces:** None — documentation only, no code interfaces produced or consumed.

- [ ] **Step 1: Write `README.md`**

```markdown
# ContactCreator

ContactCreator automates the research and prep work of relationship-based job hunting: it turns a CV into a prioritized list of relevant contacts, drafts personalized LinkedIn and email outreach for each one, and tracks replies and follow-ups. It never automates anything on LinkedIn itself (drafts are copy-paste only), and outreach is only sent after you review it.

## Setup

```bash
cp .env.example .env
```

Fill in `.env`:
- `ANTHROPIC_API_KEY` — used to parse CVs and draft outreach.
- `HUNTER_API_KEY` — used to discover contacts by company domain (free tier).
- `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_EMAIL` — a Gmail address and app password (or another SMTP account), used to send email outreach.

Then start the app:

```bash
docker compose up --build
```

Visit `http://localhost:8000/intake`.

## Running the tests

Tests run against SQLite in-memory and never call live Anthropic, Hunter, or SMTP APIs — no Docker or `.env` needed:

```bash
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
pytest -v
```

## Using it

1. **`/intake`** — upload a CV (`.txt` or `.pdf`) and answer a short questionnaire (target roles, locations, domains, seniority, tone). Claude parses it into a structured profile.
2. **`/contacts`** — enter a company domain to discover people there via Hunter.io, then generate LinkedIn/email drafts for any contact.
3. **`/outreach`** — review drafts, copy LinkedIn notes to send manually, send emails directly (subject to a daily send cap), and track replies/interviews/follow-ups due.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add root README with setup and usage instructions"
```

---

## Done Criteria for Milestone D

- [ ] CV upload accepts both `.txt` and `.pdf` files; a PDF with no extractable text gives a clear 400, not a crash.
- [ ] A Claude API failure (auth, rate limit, timeout, network) during CV parsing or drafting results in the existing clean 502 response, not an unhandled 500.
- [ ] A Hunter.io API failure (auth, rate limit, timeout, network, non-2xx response) during discovery results in a clean 502 response, not an unhandled 500.
- [ ] `hunter_client.py` has full unit test coverage (previously zero).
- [ ] `README.md` exists at the repo root with setup, test-running, and usage instructions.
- [ ] `pytest -v` passes in full.
