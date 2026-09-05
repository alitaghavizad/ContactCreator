import anthropic


class DraftingError(Exception):
    """Raised when Claude's response cannot be used for drafting."""
    pass


LINKEDIN_CHAR_LIMIT = 300


def _first_text_block(message) -> str:
    """Return the text of the first text content block in a Claude response.

    Claude responses may contain non-text blocks (e.g. thinking blocks) before
    the text block, so indexing content[0] blindly is unsafe.
    """
    for block in message.content or []:
        if getattr(block, "type", None) == "text":
            return block.text
    raise DraftingError("Claude response contained no text content block.")


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

EMAIL_SUBJECT_SYSTEM_PROMPT = """You write short, specific subject lines for cold outreach \
emails from a job seeker reaching out to someone in their target industry. The subject should \
be under 80 characters, reference something concrete and specific (not generic phrases like \
"Quick question" or "Following up"), and read naturally as an email subject line. Return ONLY \
the subject line text, no quotes, no markdown."""


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
    if not message.content:
        raise DraftingError("Claude returned an empty response with no content blocks")
    note = _first_text_block(message).strip()
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
    if not message.content:
        raise DraftingError("Claude returned an empty response with no content blocks")
    return _first_text_block(message).strip()


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
