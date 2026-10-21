# Troubleshooting

## My campaign isn't sending

Open the campaign. The banner at the top says what it's doing:

| Banner | Meaning | What to do |
|---|---|---|
| **Outside sending hours** | It's outside the campaign's window, in the campaign's time zone. The schedule under Campaign Settings also shows the window in your own time. | Wait for the time shown, or **Edit** the hours or time zone |
| **On a break** | It sent recently and is waiting out its random pause | Nothing to do. Shorten **Pause between emails** to speed up. |
| **Inbox limits reached** | Every sending inbox has hit its daily limit (shared with warmup) | Wait for the reset (midnight UTC), add inboxes, or raise limits |
| **Waiting on follow-ups** | Everyone's been emailed, and the next step isn't due yet | Nothing to do |
| **No connected inbox** | No inbox in its pool is active and connected | Reconnect on **Inboxes**, or tick another inbox |
| *Yellow "Before this campaign can send" box* | Something's missing: sequence, inboxes, leads, bad variables or the OpenAI key | Fix each item listed |

**Other things to check:**

- **Weekends:** "Send on weekends" is off by default, and it uses the campaign's time zone.
- **Is the campaign active?** Paused, draft and completed campaigns don't send.
- **Leads stopping straight away:** check the leads table's stop reason.
  - `missing_variable:first_name`: the lead has no first name. Add a fallback in the sequence, like `{{first_name|there}}`.
  - `do_not_contact`, `unsubscribed`, `bounced`: excluded on purpose.
  - `send_failed`: Gmail refused the email 3 times. Usually the inbox needs reconnecting.
  - `send_interrupted`: the backend stopped mid-send, so the lead was stopped to avoid a double send.
- **Is the backend running?** The sender is a loop inside the backend process. If it isn't running, nothing sends.
- **Two backends on port 8000?** If you started `uvicorn` twice, an old copy may be answering requests with outdated code. Check with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, stop the extras, and run a single `uvicorn app.main:app --reload --port 8000`.

## The page is blank (white screen)

Usually the frontend dev server is running with an old Tailwind config, for example after `tailwind.config.js` changed. Stop `npm run dev` with Ctrl+C and start it again.

To see the exact error, open the browser console (Cmd+Option+J), or request a stylesheet directly:

```bash
curl -s localhost:5173/src/index.css | head
```

If that returns an HTML error page mentioning a class that "does not exist", restart the dev server.

## Connecting Gmail fails

| Error | Fix |
|---|---|
| `redirect_uri_mismatch` | The redirect URI in Google Cloud must be exactly `http://localhost:8000/api/v1/inboxes/oauth/callback`, matching `GOOGLE_REDIRECT_URI` |
| "Access blocked: app not verified" or "not a test user" | Add the Gmail address under **OAuth consent screen → Test users** |
| "Gmail OAuth not configured" | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are missing from `backend/.env`. Restart the backend after adding them. |
| An inbox worked, then stopped after about a week | Google expires refresh tokens for "Testing" apps after 7 days. Reconnect the inbox, or publish the consent screen. |

The Lead Box shows a yellow banner naming any inbox that couldn't be read. Reconnect that one on **Inboxes**.

## Lead Box shows no replies

- **Only known prospects appear.** A reply shows up only if the sender's email matches someone in Prospects. Replies from colleagues, or from a different address, won't appear.
- **Last 30 days, newest 50 per inbox.** Only the newest 50 INBOX messages per account in the last 30 days are scanned, so a busy inbox can push an older reply out.
- **Archived mail.** A reply you archived in Gmail, so it's no longer in INBOX, won't show.

## The reply agent doesn't draft

- **No OpenAI key:** `OPENAI_API_KEY` must be set (the agent panel shows a red note if it isn't).
- **Auto-draft is off:** it only runs when you click.
- **Skipped on purpose:** conversations you already answered, and leads marked unsubscribed or do-not-contact.
- **Already handled:** a reply that already has a draft (or a dismissed one) isn't redrafted by batch runs. Use **Redraft** on that conversation.
- **More than 25 new replies:** the rest are picked up on the next run.

## Alert emails don't arrive

- **Not saved yet:** save your address under the agent's gear icon. That also switches alerts on.
- **Check delivery:** click **Send test**. The address under the field shows which inbox sends the alerts.
- **Spam folder:** check it, and mark the first alert "not spam".
- **What triggers an alert:** only **background** (auto-draft) runs send alerts, and only when a new draft needs a reply. Out-of-office replies alone don't trigger one.

## Emails land in spam

- **Warm up first:** let new inboxes finish warmup (about 3 weeks) before campaigns.
- **Send less:** keep daily limits low and the pause between emails at a few minutes.
- **Verify lists:** keep bounces under about 3%.
- **Write naturally:** plain-text, personal emails, without lots of links or images.
- **Authenticate your domain:** set up SPF, DKIM and DMARC if you send from a custom domain through Google Workspace.

## Resetting things

- **Stop everything:** pause each campaign, or stop the backend.
- **Fresh database:** stop the backend and move `backend/data/outbound.db` somewhere else. A new empty one is created on the next start.
- **Disconnect an inbox:** delete it on **Inboxes**, and optionally revoke access at https://myaccount.google.com/permissions.
