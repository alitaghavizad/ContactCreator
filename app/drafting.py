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
