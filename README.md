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

Visit `http://localhost:8000/` for the overview, or `/intake` to set up your profile.

## Running the tests

Tests run against SQLite in-memory and never call live Anthropic, Hunter, or SMTP APIs — no Docker or `.env` needed:

```bash
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
pytest -v
```

## Using it

1. **`/`** — see your network, outreach progress, recent activity, and next actions.
2. **`/intake`** — upload a CV (`.txt` or `.pdf`) and answer a short questionnaire (target roles, locations, domains, seniority, tone). Claude parses it into a structured profile. Existing preferences are prefilled when updating your profile.
3. **`/contacts`** — enter a company domain to discover people there via Hunter.io. Search or filter saved contacts, open their detail panels, and generate LinkedIn/email drafts.
4. **`/outreach`** — edit and save drafts, copy LinkedIn notes to send manually, review and send emails (subject to a daily send cap), and track replies/interviews/follow-ups due. Sending an email or marking a LinkedIn note as sent preserves your current edits. Sent history cannot be edited.

The UI uses local CSS, JavaScript, and SVG assets with no frontend build step. After changes to Python routes, restart the app service with `docker compose restart app`; templates and static assets are mounted from the project.
