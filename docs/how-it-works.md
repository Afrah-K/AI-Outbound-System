# How it works

For anyone changing the code, or who wants to know exactly what the system does with their inboxes.

- [Architecture](#architecture)
- [The campaign sender](#the-campaign-sender)
- [Reply and bounce detection](#reply-and-bounce-detection)
- [The reply agent](#the-reply-agent)
- [Warmup](#warmup)
- [Database](#database)

## Architecture

```
Browser (React, :5173) ──/api──▶ FastAPI (:8000) ──▶ SQLite (backend/data/outbound.db)
                                     │
                                     ├── Gmail API  (Gmail inboxes: send, read threads; your OAuth app)
                                     ├── SMTP + IMAP (any other inbox: send / read)
                                     ├── OpenAI API (gpt-4o-mini; optional)
                                     └── Public web (company sites, DuckDuckGo, Clutch)
```

- **Backend** (`backend/app`):
  - **Routers:** FastAPI routers handle HTTP (`routers/`).
  - **Logic:** business logic lives in `services/`.
  - **Mail providers** (`integrations/mail/`):
    - **Interface:** every feature talks to an inbox through one `MailProvider` interface (`base.py`). `provider_for(inbox)` returns the right implementation for that inbox.
    - **Gmail:** `integrations/gmail/service.py` wraps the Gmail API and refreshes OAuth tokens as needed. `sync_tokens` saves refreshed tokens back to the inbox row.
    - **SMTP/IMAP:** `smtp_imap.py` uses only the standard library. A message id is its `Message-ID` header, and a thread id is the first message's `Message-ID`. Folders map to Gmail-style labels: `INBOX`, `SENT`, `SPAM` (Junk), `TRASH`, plus `UNREAD`. Callers therefore never branch on the provider.
    - **Passwords:** these are Fernet-encrypted with `MAIL_CREDENTIALS_KEY` (`credentials.py`).
    - **Connected:** `Inbox.is_connected` / `has_credentials` decide whether an inbox can send, for either provider.
  - **Database:** SQLAlchemy 2 with synchronous sessions; all models are in `models/`.
- **Background loops** are started in `main.py`'s lifespan as `asyncio` tasks in the same process. There's no separate worker or queue:
  - `services/campaign_engine.py`: the sender, every 60 s, and the reply checker, every 5 min
  - `services/warmup.py`: warmup, every 30 min
  - `services/reply_agent.py`: auto-draft, every 5 min, only when switched on

  Each loop opens its own DB session. A lock in each service stops a manual "run now" from overlapping with the scheduled run.
- **Long jobs** (enrichment, Personalizer) run as FastAPI background tasks with an in-memory job store, polled by the UI. Restarting the backend loses in-progress job results, but not the database.
- **Frontend** (`frontend/src`): React 18, React Router, TanStack Query v5 and Tailwind.
  - **API calls:** all go through `services/apiClient.js`. Its error interceptor turns FastAPI's `detail` (a string, `{message, errors}`, or a validation list) into a toast.
  - **Time zones:** helpers are in `utils/time.js`.

Timestamps are stored and returned as **naive UTC**. The frontend appends `Z` when parsing (`parseUtc` in `utils/time.js`).

## The campaign sender

`run_campaign_cycle` runs every 60 seconds. For each **active** campaign, in random order so campaigns that share inboxes take turns:

1. **Activate new leads.** `pending` leads become `in_progress` at step 0. Their first send is due after step 0's delay.
2. **Check the window.** If it's outside the campaign's sending hours in its own time zone, or a weekend with weekends off, skip it.
3. **Respect the campaign's pause.** If `next_send_after` is in the future, the campaign is on a break, so skip it.
4. **Pick available inboxes.** An inbox qualifies if it's in the campaign's pool, active and connected, under its daily limit, hasn't sent from another campaign this cycle, and is past its own randomised 30–90 s gap.
5. **Send to due leads**, oldest due first. For each lead:
   - **Stop checks:** stop the lead if the person is unsubscribed, bounced, or do-not-contact, or replied (when stop-on-reply is on).
   - **Inbox choice:** follow-ups use the **same inbox** as earlier steps. If that inbox is busy, the lead waits. It only moves to another inbox if the original left the pool.
   - **Render:** render the step's template. Missing variables without a fallback stop the lead (`missing_variable:<name>`).
   - **Threading:** a follow-up with a blank or identical subject is sent as `Re: <previous subject>` in the previous Gmail thread.
   - **GPT:** GPT steps are rewritten per lead. If OpenAI fails, the lead is retried in an hour.
   - **Log, then send:** an `EmailLog` row is written as `SENDING` *before* calling Gmail, then updated to `SENT` with the Gmail message and thread IDs.
   - **Advance:** the lead moves to the next step (due after that step's delay), or is marked `completed` after the last step.
6. **Take a break.** After one successful send, if the campaign has a pause configured, set `next_send_after = now + random(min, max) minutes` and stop for this cycle.
7. **Finish.** A campaign with no pending or in-progress leads becomes `completed`.

**Failures:**

- **Gmail errors:** a failed send is retried after 30 minutes. After 3 failed attempts on the same step, the lead is stopped (`send_failed`).
- **Crash mid-send:** if the process dies between the `SENDING` row and Gmail's answer, the next cycle can't know whether the email went out. It marks the row failed and stops the lead (`send_interrupted`) rather than risk emailing a prospect twice.

**Status for the UI.** `describe_sending_state` reports what an active campaign is doing (`sending`, `on_break`, `outside_hours`, `daily_limit`, `waiting_followups`, `finishing`, `no_inboxes`) and when its next email is due. This comes back as `sending` on campaign API responses.

**Daily limits.** Each inbox's `emails_sent_today` counts campaign and warmup sends, and resets at midnight UTC.

## Reply and bounce detection

`check_replies` runs every 5 minutes. It looks at campaign threads sent in the last 30 days that haven't produced a reply or bounce yet, fetches each Gmail thread, and finds the first message from someone else:

- **Bounces:** messages from `mailer-daemon` / `postmaster`, or with subjects like "Delivery Status Notification" or "Undeliverable". These set the email to `bounced`, increment the campaign's bounce count, set the person to `bounced`, and stop the lead.
- **Auto-replies:** "Automatic reply", "Out of office" and similar are ignored, so the sequence continues.
- **Replies:** anything else sets the email to `replied`, increments the campaign's replies, sets the person to `replied` (if they were new or contacted), and stops the lead if the campaign has stop-on-reply on.

Each thread is counted once. Loading Lead Box runs the same recording logic straight away (`services/unibox.py → record_campaign_reply`), so replies don't wait for the 5-minute check.

## The reply agent

`services/reply_agent.py`. Draft-only by design: nothing in it sends email.

**Collecting conversations.** `collect_lead_replies` lists INBOX messages from the last 30 days in every connected inbox. It uses metadata-only Gmail requests, batched up to 100 per round trip. It keeps messages whose sender is a known prospect, excluding your own inboxes, and takes the newest such message per thread.

**Drafting.** For each conversation without a draft for its newest lead message:

- **Prompt:** the agent sends `gpt-4o-mini` the thread (quoted history stripped, last 8 messages), the lead's profile and company context, your saved instructions, and any one-off guidance.
- **Output:** it asks for JSON with `category`, `summary`, `suggested_status` and `draft`. Categories are interested, question, not_interested, out_of_office, unsubscribe, wrong_person and other.
- **Placeholders:** the prompt forbids inventing facts. Unknowns become `[[placeholders]]`, and the send endpoint refuses drafts that still contain `[[`.

**Storage.** Drafts are stored in `agent_drafts`, one row per lead message, with a unique `lead_message_id`, so a reply is never drafted twice by batch runs. A newer lead message supersedes the older pending draft for the same thread. Redrafting a conversation updates its row in place. A hand-written reply from Lead Box dismisses any pending draft for that thread.

**Limits.** Each run handles at most 25 conversations, 4 at a time.

**Auto mode.** When `auto_draft` is on, the background loop runs this every 5 minutes. If it drafted anything that needs a reply and alerts are on, it emails a single summary to `notify_email`, sent through the alert inbox (`services/notifications.py`, Gmail API). Alerts don't count toward inbox quotas.

Settings live in the single-row `reply_agent_settings` table. (An older, unused `agent_settings` table may exist in early databases and can be ignored.)

## Warmup

`services/warmup.py`, every 30 minutes:

1. **Check every active inbox:**
   - **Auto-pause:** on a spam report, or when the 7-day bounce rate exceeds the threshold (needs at least 5 sends).
   - **Stage:** advance it based on days since warmup started.
2. **Pick one inbox:** the eligible inbox furthest below its stage's daily quota.
3. **Exchange one email:** it sends one warmup email to a partner inbox (whichever has sent the least), and the partner replies.

This means at most one exchange happens per run, across all inboxes. Warmup sends count against each inbox's daily limit.

## Database

SQLite at `backend/data/outbound.db`. The main tables:

| Table | Holds |
|---|---|
| `inboxes` | Connected inboxes. `provider` is `gmail` (OAuth tokens) or `smtp` (server settings plus encrypted password). Also the daily limit and counter, warmup stage and health. |
| `people`, `companies` | Prospects and their companies (enrichment data, homepage text, personalisation hook) |
| `lead_lists`, `lead_list_members` | One list per CSV upload, and who was in it |
| `sequences`, `sequence_steps` | Templates. Steps are ordered by `order`, renumbered 0, 1, 2… on every change. |
| `campaigns` | Settings, pacing (`min_gap_minutes`, `max_gap_minutes`, `next_send_after`), denormalised stats |
| `campaign_inboxes` | Which inboxes a campaign sends from |
| `campaign_leads` | Each lead's progress: `current_step` (an index into the ordered steps), `status`, `next_send_at`, `stop_reason` |
| `email_logs` | Every email sent: campaign, warmup or manual reply. The provider's message and thread IDs (`gmail_*` columns; `Message-ID`s for SMTP inboxes), status, timestamps. |
| `agent_drafts`, `reply_agent_settings` | Reply agent output and settings |
| `warmup_configs`, `warmup_logs` | Warmup stage settings and history |

`send_queue` is defined but unused. The sender works from `campaign_leads.next_send_at` instead.

**Schema changes** are applied at startup by `init_db()` in `app/database.py`:

- **New tables:** `create_all()` creates any that are missing.
- **New columns:** `_add_missing_columns()` adds columns that a model gained later, using `ALTER TABLE … ADD COLUMN` with the model's scalar default. It never drops, renames or rewrites anything.
- **Renames and type changes:** these aren't handled, so avoid them on existing columns. Add a new column instead. Alembic is configured in `backend/alembic/` if you need real migrations.
