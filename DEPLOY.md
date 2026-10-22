# Deploying (free): Render + Vercel + Neon

| Part | Where | Free plan | Config |
|---|---|---|---|
| Backend (FastAPI + schedulers + job worker, one process - same as locally) | [Render](https://render.com) web service `ai-outbound-api` | Free | `render.yaml` |
| Frontend (React/Vite) | [Vercel](https://vercel.com) | Hobby | `vercel.json` |
| Database (PostgreSQL) | [Neon](https://neon.com) | Free | `DATABASE_URL` on Render |

Vercel serves the frontend and forwards every `/api/...` request to Render, so the browser only ever talks to your Vercel domain. That keeps the sign-in cookie first-party, so login works without any cross-site setup.

Locally nothing changes: `uvicorn app.main:app --reload` and `npm run dev`, on SQLite.

## Before you start: what "free" means here

- **The backend sleeps.** Render's free web services stop after **15 minutes with no visitors** and take about **a minute** to wake on the next visit. While it's asleep, scheduled work stops too: campaign sending, warmup, reply checks and inbox placement checks. They resume when someone opens the app. (An always-on backend needs Render's paid Starter plan.)
- **The first request after a sleep is slow.** If a page shows an error right after a long break, wait a minute and refresh.
- **Neon free:** 1 GB of data and 100 compute-hours a month. Because the backend sleeps when unused, the database does too (after 5 idle minutes), so normal use fits.
- **Vercel Hobby is for personal, non-commercial use** (Vercel's fair-use rules). Fine for trying it out; for business outreach Vercel expects Pro.
- **Clutch live scraping isn't available on Render** (Render's Python runtime has no Chromium, which Clutch's bot-check needs). Awwwards and Google Maps work; for Clutch use "Upload saved page(s)", or run the app locally.

## 1. Database - Neon

1. Sign up at [neon.com](https://neon.com) and create a project (free plan) in a US East region.
2. On the project dashboard click **Connect**. Copy two connection strings:
   - **Pooled** (host contains `-pooler`) - the app's `DATABASE_URL`.
   - **Direct** (pooling switched off) - for the one-off data copy in step 4.

The backend creates the tables on its first start.

## 2. Backend - Render

1. Sign up at [render.com](https://render.com) with GitHub.
2. **New → Blueprint**, pick this repo. Render reads `render.yaml` and creates the `ai-outbound-api` web service on the free plan.
3. It asks for the values marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | Neon **pooled** connection string |
   | `APP_BASE_URL` | `https://<your-vercel-domain>` (fill in after step 3, or guess it now - e.g. `https://ai-outbound-system.vercel.app`) |
   | `CORS_ORIGINS` | same as `APP_BASE_URL` |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | same OAuth client as local |
   | `GOOGLE_REDIRECT_URI` | `https://<your-vercel-domain>/api/v1/inboxes/oauth/callback` |
   | `GOOGLE_LOGIN_REDIRECT_URI` | `https://<your-vercel-domain>/api/v1/auth/google/callback` |
   | `OPENAI_API_KEY` | your key (reply agent, personalizer) |
   | `GOOGLE_MAPS_API_KEY` | optional |

   `SECRET_KEY` and `MAIL_CREDENTIALS_KEY` (which encrypts SMTP/IMAP inbox passwords) are generated for you; everything else is set in `render.yaml`. Don't regenerate `MAIL_CREDENTIALS_KEY` later. If it changes, SMTP/IMAP inboxes need their passwords re-entered.
4. Deploy, then open `https://ai-outbound-api.onrender.com/health` - it should say `{"status":"healthy"}`.

**If Render gave the service a different address** (it adds a suffix when the name is taken), change the destination in `vercel.json` to that address and push.

## 3. Frontend - Vercel

1. Sign up at [vercel.com](https://vercel.com) with GitHub (Hobby plan).
2. **Add New → Project**, import this repo, keep **Root Directory** as the repo root. `vercel.json` builds `frontend/` and forwards `/api` to Render. No environment variables are needed on Vercel.
3. Deploy. Your address is shown on the project (e.g. `https://ai-outbound-system.vercel.app`). If it differs from what you put on Render in step 2, update `APP_BASE_URL`, `CORS_ORIGINS` and the two Google redirect URIs on Render.

## 4. Copy your existing data (optional)

To start with everything you have locally (your account, prospects, campaigns, email history, connected inboxes, settings), copy the local SQLite database into Neon **before** the first sign-in. From `backend/`, using Neon's **direct** connection string:

```bash
python scripts/migrate_sqlite_to_postgres.py "<Neon direct connection string>"
```

It creates the tables, copies every row, and refuses to run if the target already has data. Rows that point at things deleted long ago (SQLite never enforced those links) have the link cleared, and the script reports how many. Connected Gmail inboxes keep working as long as Render uses the same Google OAuth client.

## 5. Google Cloud Console

On the OAuth client (**APIs & Services → Credentials**), add both production URLs under **Authorized redirect URIs** - on your **Vercel** domain, since Vercel forwards them to Render:

- `https://<your-vercel-domain>/api/v1/auth/google/callback` - "Continue with Google"
- `https://<your-vercel-domain>/api/v1/inboxes/oauth/callback` - connecting Gmail inboxes

Keep the `http://localhost:8000/...` ones for local development.

## 6. Sign in

Open `https://<your-vercel-domain>` and use **Continue with Google**, or set a password for an account from your machine:

```bash
DATABASE_URL="<Neon direct connection string>" python scripts/set_password.py you@example.com
```

## Keeping the backend awake (optional)

To keep campaigns sending when nobody has the app open, ping `https://ai-outbound-api.onrender.com/health` every 10 minutes with a free uptime monitor (e.g. UptimeRobot). One always-awake service fits in Render's 750 free hours a month. The catch: the database then never sleeps either, and Neon's 100 free compute-hours run out after roughly 2-3 weeks (Neon pauses until next month; no data is lost). For always-on sending, Render Starter + a paid Neon plan is the reliable setup.

## Troubleshooting

- **Error right after opening the site:** the backend was asleep - wait about a minute and refresh.
- **Google says `redirect_uri_mismatch`:** the URI on the Google OAuth client must match the Render variables exactly - your Vercel domain, `https`, no trailing slash.
- **Logs:** Render dashboard → `ai-outbound-api` → **Logs**.
