# Outbound

A self-hosted cold email platform that runs on your own machine. It finds and enriches leads, sends personalised email sequences from your own Gmail accounts, and collects every reply in one place. An AI agent drafts the responses, and nothing goes out without your approval.

It runs locally (a FastAPI backend with a SQLite database, and a React frontend) or deployed on Vercel with Postgres - see [DEPLOY.md](DEPLOY.md). Each account signs in with Google or email + password and gets its own separate workspace. Email is sent and read through the Gmail API with your own Google OAuth app.

## What it does

| Area | What you get |
|---|---|
| **Lead Box** (home page) | Every reply from your prospects across all connected Gmail accounts. Read the thread, reply in place, and use the reply agent to triage replies and draft responses. |
| **Inboxes & Warmup** | Connect Gmail accounts and warm them up gradually by exchanging real emails between your own inboxes. |
| **Prospects** | Your lead database. Import CSVs (each upload becomes a reusable lead list), then search, filter, and bulk-add people to campaigns. |
| **Scrapers → Enricher → Verifier** | Build lists: scrape agency directories (Clutch), find contact emails on company websites, and drop risky or undeliverable addresses. |
| **Personalizer** | Draft one-off AI emails grounded in a live crawl of each company's site and recent web mentions. |
| **Sequences** | Multi-step email templates with `{{first_name}}`-style variables, delays between steps, and optional GPT personalisation. |
| **Campaigns** | Send a sequence to a lead list from a pool of inboxes, within a sending window, with random breaks between emails. Follow-ups stop automatically when a lead replies or bounces. |
| **Analytics** | Sending volume, reply rate, and per-inbox health. |

## Quick start

You need Python 3.9+, Node 18+, a Google Cloud OAuth client (for Gmail), and optionally an OpenAI API key (for the AI features).

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for the Clutch scraper
cp .env.example .env                 # then fill in GOOGLE_CLIENT_ID / SECRET and OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173 and sign in (Google, or create an account with email + password). Then:

1. Go to **Inboxes** and connect a Gmail account.
2. Import leads on **Prospects**.
3. Write a **Sequence**.
4. Create a **Campaign**, add your lead list and inboxes, and press **Start sending**.

Full instructions, including how to create the Google OAuth app: [docs/setup.md](docs/setup.md).

## Documentation

- [Setup](docs/setup.md): installation, Google OAuth, environment variables, running.
- [User guide](docs/user-guide.md): every page, and the end-to-end workflow.
- [How it works](docs/how-it-works.md): the sending engine, reply detection, the reply agent, warmup, and the data model.
- [API reference](docs/api.md): every backend endpoint.
- [Troubleshooting](docs/troubleshooting.md): "my campaign isn't sending", a blank page, OAuth errors, and more.
- [Deploying to Vercel](DEPLOY.md): frontend, API, background worker and Postgres in one Vercel project.

Interactive API docs are also served by the backend at http://localhost:8000/docs.

## Project layout

```
backend/
  app/
    main.py              FastAPI app; runs the background worker in-process when local
    worker.py            The background worker on its own (the Vercel Daemon)
    tenancy.py           Per-account data isolation for every query
    services/jobs.py     Database-backed background jobs (scrapes, enrichment, ...)
    config.py            Settings, read from backend/.env
    database.py          SQLAlchemy engine and startup schema sync
    models/              Database tables
    routers/             HTTP API, one module per area
    services/            Business logic: campaign_engine, reply_agent, warmup, enrichment, ...
    integrations/        Gmail API client, website scraper
  scrapers/              Clutch directory scraper (Playwright)
  scripts/               One-off CLI helpers (e.g. enrich_csv.py)
  data/outbound.db       SQLite database (created on first run)
frontend/
  src/
    pages/               One file per page
    components/          Layout and shared UI (Card, Button, StatCard, ...)
    services/apiClient.js  Every API call the UI makes
    utils/               Time zone helpers
docs/                    This documentation
```
