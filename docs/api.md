# API reference

The backend is a JSON REST API at `http://localhost:8000`. Every app endpoint lives under `/api/v1`. **Interactive docs**, with request and response schemas and a "Try it out" button, are at **http://localhost:8000/docs**. This page is a map of what exists.

**Conventions:**

- **Timestamps** are naive UTC ISO strings (`2026-10-16T17:00:00`). Treat them as UTC.
- **Errors** return `{"detail": ...}`. The detail is a string, a validation list (422), or for campaign start/resume `{"message": "...", "errors": ["...", ...]}`.
- **Paging:** list endpoints take `skip` and `limit` and return `total`.
- **No authentication.** The API is meant to run on localhost only. Don't expose port 8000 to the internet.

## Inboxes: `/api/v1/inboxes`

| Method | Path | What it does |
|---|---|---|
| GET | `/inboxes` | List inboxes with limits, today's sends, warmup stage and health |
| GET | `/inboxes/{id}` | One inbox |
| DELETE | `/inboxes/{id}` | Remove an inbox |
| GET | `/inboxes/oauth/initiate` | Start Gmail OAuth. Returns `auth_url`. |
| GET | `/inboxes/oauth/callback` | OAuth redirect target. Saves tokens, then redirects to `APP_BASE_URL/inboxes`. |
| POST | `/inboxes/{id}/test` | Verify credentials by fetching the Gmail profile |
| POST | `/inboxes/{id}/send-test?to=` | Send a real test email |

## Warmup: `/api/v1/warmup`

| Method | Path | What it does |
|---|---|---|
| GET | `/warmup/status` | Per-inbox stage, today's count vs quota, pause state |
| GET | `/warmup/activity?limit=` | Recent warmup events |
| POST | `/warmup/run` | Run one warmup cycle now |
| POST | `/warmup/{inbox_id}/pause`, `/resume` | Pause or resume warmup for an inbox |
| POST | `/warmup/{inbox_id}/cancel` | End warmup for an inbox: resets progress and keeps it stopped until resumed |

## Prospects and lead tools: `/api/v1/leads`

| Method | Path | What it does |
|---|---|---|
| GET | `/leads/people` | Prospects, newest first. Filters: `search` (name, email, role, company), `status`, `list_id`. Each row includes company details and `campaign_count`. The response also has `status_counts` and `total_prospects`. |
| GET | `/leads/people/{id}` | One prospect |
| PATCH | `/leads/people/{id}/status?status=` | Set a prospect's status |
| POST | `/leads/people/bulk-status` | `{person_ids, status}`: set many at once |
| GET | `/leads/companies`, `/leads/companies/{id}` | Companies, and one company with its people |
| POST | `/leads/import?update_existing=&list_name=` | CSV upload (multipart `file`). Creates a lead list and returns counts plus `lead_list_id`. |
| GET | `/leads/lists` | Uploaded lead lists with sizes, plus `total_prospects` |
| DELETE | `/leads/lists/{id}` | Delete a list. The prospects are kept. |
| POST | `/leads/companies/{id}/enrich` | Enrich one company now |
| POST | `/leads/enrich/pending` | Enrich every not-yet-enriched company (background) |
| POST | `/leads/enrich/upload` | Upload a company CSV to enrich (background job) |
| GET | `/leads/enrich/jobs/{job_id}` | Poll an enrichment job |
| POST | `/leads/verify` | Check deliverability, drop generic duplicates, tag segments |
| POST | `/leads/personalize` | `{leads, offer}`: AI-draft one email per lead (background job, max 200) |
| GET | `/leads/personalize/jobs/{job_id}` | Poll a personalisation job |

## Sequences: `/api/v1/sequences`

| Method | Path | What it does |
|---|---|---|
| GET | `/sequences` | List, with step and campaign counts |
| POST | `/sequences` | Create, optionally with `steps` |
| GET | `/sequences/variables` | Supported template variables, aliases and fallback syntax |
| GET | `/sequences/{id}` | One sequence, with its ordered steps and the campaigns using it |
| PUT | `/sequences/{id}` | Update the name or description. Send `steps` to replace the step list; existing step rows are kept, matched by `id` or by position. |
| DELETE | `/sequences/{id}` | Delete. Returns 409 while an active or paused campaign uses it. |
| POST | `/sequences/{id}/duplicate` | Copy the sequence with its steps |
| POST | `/sequences/{id}/steps` | Add a step (at `order`, else at the end) |
| PUT / DELETE | `/sequences/{id}/steps/{step_id}` | Edit or remove a step |
| POST | `/sequences/{id}/steps/reorder` | Body: every step id, in the new order |

Unknown `{{variables}}` in a subject or body are rejected with 400.

## Campaigns: `/api/v1/campaigns`

| Method | Path | What it does |
|---|---|---|
| GET | `/campaigns?status=` | List. Each item includes `sending`: `{state, next_send_at}`. |
| POST | `/campaigns` | Create (draft). Fields: name, description, sequence_id, `send_start_time` / `send_end_time` (HH:MM), timezone (IANA), send_on_weekends, stop_on_reply, `min_gap_minutes` / `max_gap_minutes` (0–240). |
| GET | `/campaigns/{id}` | Details: settings, stats, inboxes, `sending`, `next_send_after`, and `readiness_errors` (for drafts and paused campaigns) |
| PUT | `/campaigns/{id}` | Update settings. The sequence can't change while the campaign is active. |
| DELETE | `/campaigns/{id}` | Delete. It must not be active; email history is kept. |
| POST | `/campaigns/{id}/start` | Activate. Returns 400 with `errors` listing anything missing. |
| POST | `/campaigns/{id}/pause`, `/resume`, `/archive` | Change status |
| GET | `/campaigns/{id}/stats` | Lead status breakdown, stop reasons, per-step sends, reply and bounce rates |
| GET | `/campaigns/{id}/activity` | Emails sent or attempted, newest first |
| GET | `/campaigns/{id}/preview?step=&person_id=` | Render a step for a lead. Returns `missing_variables` and `unknown_variables`. |
| GET | `/campaigns/{id}/leads?status=&skip=&limit=` | The campaign's leads, with progress and stop reason |
| POST | `/campaigns/{id}/leads` | Body: `[person_id, ...]`. Add specific prospects. |
| POST | `/campaigns/{id}/leads/from-list` | `{list_id}`: add a lead list. `null` adds every prospect. |
| POST | `/campaigns/{id}/leads/upload` | CSV upload: import, then add everyone in the file |
| DELETE | `/campaigns/{id}/leads` | Body: `[person_id, ...]`. Remove from the campaign. |
| POST | `/campaigns/{id}/leads/{person_id}/stop` | Stop one lead's sequence |
| POST | `/campaigns/{id}/inboxes` | Body: `[inbox_id, ...]`. Replace the sending pool. |
| POST | `/campaigns/run-cycle` | Run one sending pass now |
| POST | `/campaigns/check-replies` | Scan for replies and bounces now |

Adding leads returns `{added, skipped: {not_found, already_in_campaign, uncontactable}}`.

## Lead Box and the reply agent: `/api/v1/unibox`

The URL prefix keeps the page's original name, "Unibox".

| Method | Path | What it does |
|---|---|---|
| GET | `/unibox/replies?days=&per_inbox=` | Conversations where a known prospect wrote back, one per thread, with person, campaign and the agent's latest draft. Also records new campaign replies. |
| GET | `/unibox/threads/{inbox_id}/{thread_id}` | Full thread, plus `person`, `campaign` and `agent` |
| POST | `/unibox/threads/{inbox_id}/{thread_id}/reply` | `{to, body, subject?}`: send a threaded reply (dismisses any pending draft) |
| GET | `/unibox/messages?per_inbox=` | Raw merged INBOX feed across accounts. Not used by the UI. |
| GET / PUT | `/unibox/agent/settings` | `instructions`, `auto_draft`, `email_alerts_enabled`, `notify_email`, `alert_inbox_id` |
| POST | `/unibox/agent/test-alert` | Send a test alert email |
| POST | `/unibox/agent/run` | Draft every reply without a draft (max 25 per run) |
| POST | `/unibox/agent/threads/{inbox_id}/{thread_id}/draft` | `{guidance}`: draft or redraft one conversation |
| GET | `/unibox/agent/drafts?status=pending` | Drafts |
| PUT | `/unibox/agent/drafts/{id}` | Save edits |
| POST | `/unibox/agent/drafts/{id}/send` | `{body?}`: approve and send. Refused if the body still contains `[[`. |
| POST | `/unibox/agent/drafts/{id}/dismiss` | Discard |

## Scrapers: `/api/v1/scrapers`

| Method | Path | What it does |
|---|---|---|
| GET | `/scrapers` | Available scrapers and their parameters |
| POST | `/scrapers/clutch/run` | Scrape Clutch category URLs live (Playwright) |
| POST | `/scrapers/clutch/parse` | Parse saved Clutch `.html` pages |

## Analytics and system

| Method | Path | What it does |
|---|---|---|
| GET | `/analytics/dashboard` | Today and 7-day sends and replies, reply rate, active campaigns and inboxes, average health |
| GET | `/analytics/inboxes?days=` | Per-inbox performance |
| GET | `/analytics/campaigns` | Per-campaign performance |
| GET | `/analytics/daily` | Daily sends and replies (chart data) |
| GET | `/analytics/health-scores` | Inbox health scores |
| GET | `/system/health`, `/system/status`, `/system/config` | Health check, counts, public config |
| GET | `/health` | Liveness check |
