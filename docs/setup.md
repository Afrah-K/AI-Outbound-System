# Setup

This guide takes you from a fresh clone to sending your first campaign.

## Requirements

- **Python 3.9 or newer**, for the backend
- **Node.js 18 or newer**, for the frontend
- **A Google account and a Google Cloud project**, to send and read mail through the Gmail API
- **An OpenAI API key** (optional), for the reply agent, the Personalizer, GPT-personalised sequence steps, and enrichment summaries. Everything else works without it.

## 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium         # only needed for the Clutch scraper
cp .env.example .env
```

Fill in `backend/.env` (see [Environment variables](#environment-variables)), then start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

The first start creates `backend/data/outbound.db` and the tables. It also starts four background loops:

| Loop | How often | What it does |
|---|---|---|
| Campaign sender | every 60 s | Sends due campaign emails |
| Reply checker | every 5 min | Spots replies and bounces, and stops those leads' sequences |
| Warmup | every 30 min | Exchanges warmup emails between your inboxes |
| Reply agent | every 5 min | Drafts responses to new lead replies. Only runs when "Auto-draft" is on; it never sends. |

Check it's running: http://localhost:8000/health should return `{"status": "healthy"}`. Interactive API docs are at http://localhost:8000/docs.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server forwards every `/api` request to `http://localhost:8000`, so both must be running.

## 3. Google OAuth (to connect Gmail)

The app sends and reads mail as you, through your own Google Cloud OAuth app. This is a one-time setup.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, or pick an existing one.
2. Go to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Go to **APIs & Services → OAuth consent screen**:
   - User type: **External** (or Internal for a Google Workspace org).
   - Fill in the app name and your email.
   - Scopes: add `gmail.send`, `gmail.readonly` and `userinfo.email`.
   - **Test users**: add every Gmail address you plan to connect. While the app is in "Testing", only these accounts can sign in.
4. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**.
   - Authorized redirect URI: `http://localhost:8000/api/v1/inboxes/oauth/callback`
5. Copy the **Client ID** and **Client secret** into `backend/.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then restart the backend.
6. In the app, go to **Inboxes → Add Inbox** and sign in with each account.

> **Heads-up: tokens expire after 7 days while the app is in Testing.** Google expires refresh tokens for unverified "Testing" apps after 7 days, so you'll need to reconnect each inbox weekly. Publishing the consent screen avoids this. For personal use that's usually just a button, though Google may show an "unverified app" warning.

The app asks only for `gmail.send` and `gmail.readonly`, so it can't delete mail or change labels. One side effect: opening a message in Lead Box doesn't mark it as read in Gmail.

## Environment variables

All of these go in `backend/.env`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | yes | - | OAuth client ID from step 3 |
| `GOOGLE_CLIENT_SECRET` | yes | - | OAuth client secret from step 3 |
| `GOOGLE_REDIRECT_URI` | no | `http://localhost:8000/api/v1/inboxes/oauth/callback` | Must exactly match the redirect URI registered in Google Cloud |
| `OPENAI_API_KEY` | for AI features | - | Reply agent, Personalizer, GPT sequence steps, enrichment summaries (model: `gpt-4o-mini`) |
| `DATABASE_URL` | no | `sqlite:///./data/outbound.db` | Database location (relative to `backend/`) |
| `SECRET_KEY` | no | `change-me-in-production` | Signs the OAuth state parameter. Set any long random string. |
| `APP_BASE_URL` | no | `http://localhost:5173` | Where the frontend runs. Used for the OAuth redirect back to the app and for links in agent alert emails. |
| `DEBUG` | no | `false` | `true` logs every SQL statement |
| `DEFAULT_DAILY_LIMIT` | no | `20` | Daily send cap for an inbox that has no limit of its own |
| `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS` | no | `30` / `90` | Minimum random gap between two campaign sends from the **same inbox** |

Campaign-specific settings (sending hours, time zone, the pause between emails, stop-on-reply) are set per campaign in the UI, not here.

## Data and backups

Everything lives in one SQLite file: `backend/data/outbound.db`. To back up, stop the backend and copy that file. To start fresh, stop the backend and move the file away; a new empty one is created on the next start.

Schema changes are applied automatically at startup. New tables are created, and columns added to existing tables are added in place. Nothing is ever dropped or rewritten. See [How it works → Database](how-it-works.md#database).

## Updating

```bash
git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install
```

Restart both servers afterwards. **Always restart the frontend dev server after `tailwind.config.js` changes.** A long-running `npm run dev` keeps the old Tailwind config and can render a blank page.
