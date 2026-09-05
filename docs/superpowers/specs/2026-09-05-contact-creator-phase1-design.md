# ContactCreator — Phase 1 Design

## Context

The user is a 29-year-old Iranian software developer (~5 years Java, ~1 year AI automation engineering, domain expertise in banking and call-center systems), recently relocated to Yerevan, Armenia, targeting local or EU roles (any work arrangement: remote/hybrid/onsite). After ~300 LinkedIn applications and 0 interviews, the working hypothesis is that many listings are low-signal ("ghost" postings or high-competition black holes), and that warm outreach to people already in the industry is a more effective channel than cold applications.

ContactCreator is a tool to automate the *research and prep* work of relationship-based job hunting — finding relevant people, drafting personalized outreach, and tracking follow-ups — while keeping a human in the loop for anything that touches LinkedIn directly (to avoid ToS violations and account bans) and for anything irreversible (sending).

This spec covers **Phase 1**: a single-user tool, built so that Phase 2 (multi-user product with auth) can be added without rewriting the core.

## Goals (Phase 1)

- Go from "CV + a few questions" to a working, prioritized list of relevant contacts with drafted, personalized outreach — with minimal manual list-building.
- Support both LinkedIn (draft-only, human sends) and email (drafted, can be auto-sent with rate limits) as outreach channels.
- Track outreach status and surface follow-ups that are due, so nothing falls through the cracks.
- Stay within free-tier tool budgets (Apollo.io free tier for discovery/enrichment).
- Build the data model and code so Phase 2 (multi-user, auth, web product) is additive, not a rewrite.

## Non-goals (Phase 1)

- No authentication / multi-user UI (schema supports it via `user_id`, but only one implicit user exists).
- No automated LinkedIn actions (no auto-connect, no auto-DM, no scraping LinkedIn directly) — LinkedIn ToS violation and account-ban risk.
- No automated inbox-reading / reply-detection — reply status is updated manually by the user. Reading someone's email inbox automatically is a much bigger trust/security surface than is justified for Phase 1.
- No support for paid discovery tools (Sales Navigator, Apollo paid tier) — free tier only for now.

## Architecture

Containerized service, run via `docker-compose up`:

```
Intake  →  Discovery/Enrichment  →  Drafting  →  Outreach  →  Tracking/Follow-up
(CV+Q&A)   (Apollo.io people      (Claude API)  (LinkedIn      (Postgres,
            search API)                          draft-copy /   follow-up
                                                   email auto-   queue)
                                                   send)
```

- **App container:** Python + FastAPI, server-rendered HTML (Jinja2 + HTMX) for the UI — no SPA framework needed for a single-user tool that will later just gain a login screen in front of the same routes.
- **DB container:** Postgres.
- **Secrets:** `.env` file (Apollo API key, Claude API key, email credentials), mounted into the container, never committed.
- Every table includes a `user_id` column from day one, even though Phase 1 has exactly one implicit user — this is what makes Phase 2 additive.

## Data Model

- **users** — `id`, `email`, `created_at`. Phase 1: single row. Phase 2: real accounts/auth.
- **profiles** — `user_id`, raw CV text, structured profile extracted via Claude (skills, years of experience, domains such as banking/call-center, target roles, target locations, seniority, tone preference for outreach).
- **companies** — `id`, `name`, `domain`, `location`, `industry`, `source` (e.g. `apollo`, `manual`).
- **contacts** — `id`, `company_id`, `user_id`, `name`, `title`, `linkedin_url`, `email`, `discovery_source`.
- **outreach_messages** — `id`, `contact_id`, `channel` (`linkedin` | `email`), `draft_text`, `status` (`drafted` | `sent` | `replied` | `no_response` | `interview` | `rejected` | `failed`), `sent_at`, `follow_up_due_at`.
- **events** — append-only log: `contact_id`, `type`, `note`, `timestamp`. Drives the follow-up queue and gives a timeline per contact (e.g. "marked sent on LinkedIn," "replied," "email bounced").

## Component Workflow

### 1. Intake (one-time setup, redone when CV changes)

Web form: upload CV (PDF or plain text) and answer a short questionnaire — target roles, target locations (e.g. "Yerevan" + "EU remote"), target domains (banking, call-center tech), seniority, outreach tone preference. Claude parses the CV into the structured `profiles` record.

### 2. Target discovery (automatic — no manual company list required)

The tool translates intake criteria directly into an Apollo.io people-search query (filtering by title, location, industry, company size) and pulls matching people (name, title, company, LinkedIn URL, verified email). No manual company-by-company entry is required by default. The user may optionally add specific "dream list" companies to prioritize, but this is opt-in.

Apollo free-tier credit usage is tracked locally (a running counter with the monthly reset date), and the UI clearly shows remaining credits before a search would exceed them — the tool blocks/warns rather than silently failing or overspending credits.

### 3. Drafting

For each newly discovered contact, Claude generates:
- A short LinkedIn connection note (≤300 characters, enforced).
- A longer, more detailed email draft.

Both reference specific details from the user's actual CV and something specific about the company/role — not a generic template. All drafts land in a review queue; nothing is sent without the user seeing it first.

### 4. Outreach

- **LinkedIn:** the UI shows the draft with a "copy" action. The user manually opens the profile, pastes, and sends in LinkedIn itself, then clicks "mark as sent" in the tool. No automated interaction with LinkedIn's UI or API.
- **Email:** the user reviews the draft and clicks "send." The tool sends via a configured Gmail API (OAuth) or SMTP account, enforcing a daily send cap (default 20/day, configurable) in code — not just as a suggestion — to protect the user's own email reputation.

### 5. Tracking & follow-up

A daily view shows: drafts awaiting review, follow-ups due (default: no reply after 6 business days, configurable), and a simple funnel count (contacted → replied → interview). The user manually updates status when someone replies — Phase 1 does not read any inbox automatically.

## Compliance & Data Handling

- Only stores data needed for outreach: name, title, company, email, LinkedIn URL, and outreach history. No broader profile scraping or data aggregation.
- A "delete this contact's data" action is available per contact — reasonable practice given outreach targets EU-based individuals, even for an individual (non-commercial) doing personal job-search outreach.
- No automation touches LinkedIn's own systems (no auto-connect, no scraping, no scripted messaging) — this is the main protection against account restriction.

## Tech Stack Summary

| Concern | Choice |
|---|---|
| Backend | Python + FastAPI |
| DB | Postgres (Docker Compose) |
| Frontend | Jinja2 + HTMX (server-rendered) |
| AI (CV parsing, drafting) | Claude API |
| Discovery/enrichment | Apollo.io API (free tier) |
| Email sending | Gmail API (OAuth) or SMTP app password, user's choice at setup |
| Secrets | `.env`, mounted, not committed |
| Packaging | Docker Compose (app + db containers) |

## Testing Strategy

- Unit tests for the Apollo query-builder logic and the credit-tracking counter (deterministic, no live API calls).
- Integration test for the drafting pipeline with the Claude API mocked (verifies prompt construction and character-limit enforcement for LinkedIn drafts).
- No tests hit live third-party APIs in CI, to avoid burning Apollo credits or sending real emails.

## Error Handling

- Apollo credit exhaustion: clear in-UI message ("Out of credits, resets on \<date\>"), search blocked rather than failing silently or erroring.
- Email send failure (bounce, auth error): message status set to `failed` with the underlying error visible in the UI — never silently dropped.
- Claude API failure during drafting: contact remains in a "needs draft" state with a visible error, retryable from the UI.

## Phase 2 (future, out of scope for this spec)

- Add authentication (email/password or OAuth) and a real multi-user web product.
- Because every table already carries `user_id` and no business logic hardcodes a single user, Phase 2 is expected to be additive: a login/session layer in front of the existing routes, plus per-user scoping on existing queries (mostly already required by the schema).
- Potential future enhancements (not committed): warm/priority tagging of contacts, LinkedIn Sales Navigator support if budget allows, semi-automated reply detection with explicit user-granted inbox access.
