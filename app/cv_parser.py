import io
import json
from dataclasses import dataclass, field

import anthropic
from pypdf import PdfReader


class CVParseError(Exception):
    """Raised when Claude's response cannot be parsed as valid JSON."""
    pass


class CVExtractionError(Exception):
    """Raised when text cannot be extracted from an uploaded CV file."""
    pass


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_texts = [page.extract_text() for page in reader.pages]
    except Exception as e:
        # Broad catch is intentional and scoped to this one function: pypdf can raise
        # all sorts of things here that aren't PyPdfError subclasses (e.g.
        # pypdf.errors.DependencyError for AES-encrypted PDFs when `cryptography` isn't
        # installed, or raw KeyError/struct.error/zlib.error from corrupt/hostile input
        # during page extraction). Every failure at this boundary means the same thing
        # to the caller: "could not read this PDF".
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


def _first_text_block(message) -> str:
    """Return the text of the first text content block in a Claude response.

    Claude responses may contain non-text blocks (e.g. thinking blocks) before
    the text block, so indexing content[0] blindly is unsafe.
    """
    for block in message.content or []:
        if getattr(block, "type", None) == "text":
            return block.text
    raise CVParseError("Claude response contained no text content block.")


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
    raw_text = _first_text_block(message)
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise CVParseError(f"Claude did not return valid JSON: {raw_text!r}") from e
    return StructuredProfile(
        skills=data.get("skills", []),
        years_experience=int(data.get("years_experience", 0)),
        domains=data.get("domains", []),
        target_roles=data.get("target_roles", []),
        target_locations=data.get("target_locations", []),
        seniority=data.get("seniority", "mid"),
        tone=data.get("tone", "professional"),
    )
