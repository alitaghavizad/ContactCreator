import json
from dataclasses import dataclass, field

import anthropic


class CVParseError(Exception):
    """Raised when Claude's response cannot be parsed as valid JSON."""
    pass

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
