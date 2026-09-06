# UI redesign

1. [x] Inspect routes, data models, templates, tests, and relevant cross-project lessons.
2. [x] Build a shared responsive shell with warm neutral surfaces, green accents, accessible controls, and local assets.
3. [x] Implement overview metrics/actions, searchable contacts/detail panels, editable outreach, and profile setup.
4. [x] Complete final regression checks and desktop inspection. Mobile testing excluded at the user's request.

Acceptance: existing discovery/intake/generation/status/send routes remain compatible; dashboard uses real records; search/filter/details work; draft edits persist and are used when sending; errors and loading states are visible; desktop keyboard navigation works; no external messaging during validation. Responsive styling is included, but mobile testing is deferred at the user's request.

Scope: redesign the existing FastAPI/Jinja application in place, retaining its database and integrations. No hosting migration. Existing Ali signature fix stays intact. Browser fixtures, if needed, use an isolated database.

Validation: 113 tests passed. Desktop browser checks passed for all four screens, contact search/no-results/filter reset/detail drawer, keyboard dismissal, inline service errors, draft save/reload, copy, send confirmation/cancellation, mocked send, reply transition, and edited LinkedIn mark-as-sent. No browser console errors. Production app restarted; data was preserved. All mutation checks used isolated in-memory fixtures with mocked SMTP and discovery. Existing empty states were covered by route tests. Mobile visual testing was intentionally omitted.
