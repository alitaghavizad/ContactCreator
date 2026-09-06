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
