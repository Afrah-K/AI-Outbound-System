# Deploying to Vercel

The whole app runs in one Vercel project, on one domain:

| Part | Runs as | Config |
|---|---|---|
| Frontend (React/Vite, `frontend/`) | Vercel **Service** `web`, served at `/` | `vercel.json` |
| API (FastAPI, `backend/`) | Vercel **Service** `api`, serverless, gets every `/api/...` request | `vercel.json` |
| Background worker (campaign sending, warmup, reply agent, placement checks, scrapes/enrichment jobs) | Vercel **Daemon** `worker`, one always-on instance | `backend/Dockerfile.worker` |
| Database | **Postgres** (Neon, from the Vercel Marketplace) | `DATABASE_URL` |

Because the frontend and API share a domain, the sign-in cookie works without any cross-site setup.

> Services and Daemons are Vercel **beta** features (available on all plans). Daemons only run on **production** deployments, so on preview deployments the API works but queued jobs and scheduled sending don't run.

Locally nothing changes: `uvicorn app.main:app --reload` still runs the API, the schedulers and the job worker in one process, on SQLite.

## 1. Create the project

1. Push this repo to GitHub.
2. In Vercel: **Add New → Project**, import the repo. Leave **Root Directory** as the repo root (Daemons don't work with a subfolder root). Vercel reads `vercel.json` and builds both services and the worker.

## 2. Add a Postgres database

In the project: **Storage → Create / Connect → Neon (Postgres)**. This adds `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct) to the project's environment variables. The app turns `postgres://` URLs into what SQLAlchemy expects by itself.

The worker creates the tables on its first start.

## 3. Environment variables

**Settings → Environment Variables** (Production):

| Variable | Value |
|---|---|
| `SECRET_KEY` | a long random string: `openssl rand -hex 32` |
| `APP_BASE_URL` | `https://<your-domain>` (e.g. `https://ai-outbound-system.vercel.app`) |
| `CORS_ORIGINS` | `https://<your-domain>` |
| `SESSION_COOKIE_SECURE` | `true` |
| `BACKGROUND_WORKER` | `external` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | same OAuth client as local |
| `GOOGLE_REDIRECT_URI` | `https://<your-domain>/api/v1/inboxes/oauth/callback` |
| `GOOGLE_LOGIN_REDIRECT_URI` | `https://<your-domain>/api/v1/auth/google/callback` |
| `OPENAI_API_KEY` | your key (reply agent, personalizer) |
| `GOOGLE_MAPS_API_KEY` | optional - users can also paste their own on the Scrapers page |
| `INITIAL_OWNER_EMAIL` | only needed if you *don't* copy your local data (step 5) |

Redeploy after changing environment variables.

## 4. Google Cloud Console

On the OAuth client (**APIs & Services → Credentials**), add both production URLs under **Authorized redirect URIs**:

- `https://<your-domain>/api/v1/auth/google/callback` - "Continue with Google" sign-in
- `https://<your-domain>/api/v1/inboxes/oauth/callback` - connecting Gmail inboxes

Keep the `http://localhost:8000/...` ones for local development.

## 5. Copy your existing data (optional)

To start production with everything you have locally (your account, prospects, campaigns, email history, connected inboxes, settings), copy the local SQLite database into the new Postgres **before** the first sign-in on production. From `backend/`, using the *unpooled* URL from step 2:

```bash
python scripts/migrate_sqlite_to_postgres.py "<DATABASE_URL_UNPOOLED>"
```

It creates the tables, copies every row, and refuses to run if the target already has data. Rows that point at things deleted long ago (SQLite never enforced those links) have the link cleared, and the script reports how many.

Connected Gmail inboxes keep working after the copy as long as `GOOGLE_CLIENT_ID`/`SECRET` are the same OAuth client.

## 6. Sign in

Open `https://<your-domain>` and use **Continue with Google**, or set a password for an account from your machine:

```bash
DATABASE_URL="<DATABASE_URL_UNPOOLED>" python scripts/set_password.py you@example.com
```

## Plans and limits

- **Hobby (free):** works. The worker counts against the Daemons quota of **10 Active CPU-hours per month**; time spent waiting doesn't count, so a mostly idle worker fits, but heavy scraping/enrichment uses it up faster. When the quota runs out, Vercel stops the worker until the next month (sending and jobs pause; the site keeps working).
- **Pro:** no such cap (billed by usage), and API requests can run up to 800s instead of 300s.

## What's different from running locally

- **Clutch scraper:** runs in the worker, inside a virtual display (Clutch's bot check needs a real browser window). Clutch may still block datacenter IPs; if scrapes come back empty, use "Upload saved page(s)" on the Scrapers page.
- **Uploads** are limited to 4.5 MB per request on Vercel (fine for CSV lead lists).
- **Logs:** the API's and the worker's output are both in the project's **Logs** tab.
