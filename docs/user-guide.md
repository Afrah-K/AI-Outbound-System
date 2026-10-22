# User guide

How to use each part of Outbound, in the order you'll usually need it.

- [The workflow at a glance](#the-workflow-at-a-glance)
- [Inboxes](#inboxes)
- [Warmup](#warmup)
- [Building a lead list: Scrapers → Enricher → Verifier](#building-a-lead-list)
- [Prospects](#prospects)
- [Sequences](#sequences)
- [Campaigns](#campaigns)
- [Lead Box and the reply agent](#lead-box-and-the-reply-agent)
- [Personalizer](#personalizer)
- [Analytics](#analytics)
- [Book a Call and Calendar](#book-a-call-and-calendar)

## The workflow at a glance

1. **Connect inboxes** on Inboxes, and let new ones warm up for a couple of weeks.
2. **Get leads**: import a CSV on Prospects, or build one with Scrapers → Enricher → Verifier.
3. **Write a sequence**: a first email plus follow-ups, using variables like `{{first_name}}`.
4. **Create a campaign**: pick the sequence, add a lead list, choose sending inboxes, and press **Start sending**.
5. **Handle replies in Lead Box**: the agent drafts responses, and you approve and send them.

## Inboxes

Connect the mail accounts you send from. There are two ways:

- **Connect Gmail:** for Gmail and Google Workspace accounts. You sign in with Google; the one-time Google Cloud setup is in [Setup](setup.md#3-google-oauth-to-connect-gmail).
- **Connect SMTP/IMAP inbox:** for any other provider, such as Zoho, Fastmail, a cold-email inbox provider or your own mail server.
  1. Enter the email address and the password. Many providers need an *app password* here.
  2. Pick your provider to fill in the server settings, or type in the SMTP and IMAP settings your provider gives you.
  3. Both logins are tested before the inbox is saved. If one fails, the form tells you which one and why.
  4. To change the server settings or password later, use **Settings** on the inbox card.
  5. The server needs `MAIL_CREDENTIALS_KEY` set first ([Setup](setup.md#4-smtpimap-inboxes-any-other-mail-provider)).

Both kinds work the same way everywhere: campaigns, warmup, Lead Box, the reply agent and placement tests. Daily limits, warmup stages and health scores apply equally. The badge on each card shows which kind it is.

Each inbox card shows:

- **Sent today / daily limit**: how many emails it has sent today out of its cap, counting campaign and warmup emails together. The counter resets at midnight UTC.
- **Health**: a 0–100 score.
- **Warmup stage**.
- **Status**: active or not.

**Test** checks the connection. **Send test email** sends a real message to an address you choose.

> **Tip:** keep daily limits modest (20–40 for a warmed-up Gmail account). Sending too much, too soon, from a new account is the fastest way into spam folders.

## Warmup

New inboxes have no sending history, so mailbox providers distrust them. Warmup builds that history by exchanging real emails between your **own** connected inboxes. Each one sends a short note, and the partner replies.

| Stage | Warmup emails per day | Lasts |
|---|---|---|
| Stage 1 | 5 | 7 days |
| Stage 2 | 10 | 7 days |
| Stage 3 | 20 | 7 days |
| Completed | - | Ready for full volume |

- **Needs a partner:** warmup needs at least **two connected inboxes**, since they warm each other up.
- **Pace:** it runs every 30 minutes and sends at most one exchange per run, so volume spreads across the day.
- **Auto-pause:** an inbox pauses automatically on a spam report, or when its bounce rate gets too high. You can pause or resume any inbox by hand, or trigger a run right away.

## Building a lead list

Three tools that chain together. Each can also be used on its own with a CSV you already have.

### Scrapers

Pulls agency listings (name, website, location, rating, category) from **Clutch.co** directory pages.

- **Live mode:** paste category URLs and run. This needs `playwright install chromium`, and Clutch sometimes blocks automated browsing.
- **Fallback:** save the directory pages from your browser (**File → Save Page As…**) and upload the `.html` files.

Results can be downloaded as CSV or sent straight to the Enricher.

### Enricher

Upload a list of companies (name plus website). For each one, it visits the company's site and collects public contact emails and homepage text. That text later helps personalisation.

The enricher runs in the background, so large lists are fine. You'll see a live count of companies processed, emails found, and the hit rate. Companies already enriched come back instantly from cache. Results can be downloaded or sent to the Verifier.

### Verifier

Cleans a list before it goes anywhere near a campaign:

- **Checks each address:** valid syntax, and a domain that exists and accepts mail (DNS/MX).
- **Drops generic addresses** (`info@`, `hello@`, …) when the same company has a personal one, but keeps them when they're the only contact.
- **Tags a segment** for each lead.

It doesn't probe individual mailboxes, so it catches typos, dead domains and role accounts, but it can't promise a specific mailbox exists. Download the clean list and import it on Prospects.

> Keeping bounces under about 3% protects your sending reputation, so verify every list before sending to it.

## Prospects

Your lead database.

- **Import CSV:** needs an `email` column. Optional columns: `first_name`, `last_name`, `company` / `company_name`, `website` / `domain`, `title` / `role`, `linkedin`, `phone`. Apollo exports work as-is.
  - **Lead list:** each upload is saved as a lead list, named after the file or a name you give it. A campaign can then target exactly that upload.
  - **Existing prospects:** "Update existing prospects" refreshes people already in the database. They're matched by email, ignoring case.
- **Summary cards:** total prospects, not contacted yet, contacted, and replied/converted.
- **Search:** matches name, email, role and company.
- **Filters:** narrow by **status** or **lead list**.
- **Table:** 30 per page. Each row shows the person, company (domain and industry), role, status, how many campaigns they're in, date added, and website / LinkedIn links.
- **Bulk actions:** tick rows (or the header box for the whole page) to **add them to a campaign** or **change their status**. Selections carry across pages.

**Statuses**:

| Status | Meaning |
|---|---|
| `new` | Never emailed |
| `contacted` | Emailed, no reply yet |
| `replied` | Wrote back |
| `converted` | Interested / became a customer |
| `bounced` | The address bounced |
| `unsubscribed` | Asked to stop |
| `do_not_contact` | Never email them |

Prospects that are unsubscribed, bounced or do-not-contact are never added to a campaign, and they're stopped if they're already in one.

## Sequences

A sequence is the series of emails a campaign sends: a first email plus any number of follow-ups.

For each step you set:

- **Wait**: days and hours after the previous step. For the first step, this counts from when the lead joins the campaign.
- **Subject**: leave it **blank on a follow-up** to reply in the same thread as the previous email ("Re: …").
- **Body**: plain text.
- **Use GPT to personalise**: rewrites the draft for each lead using their company's details, keeping your offer and call to action. This needs `OPENAI_API_KEY`.

### Template variables

| Variable | Fills in |
|---|---|
| `{{first_name}}`, `{{last_name}}`, `{{full_name}}` | The lead's name |
| `{{email}}` | The lead's email |
| `{{role}}` (or `{{title}}`) | Job title |
| `{{company_name}}` (or `{{company}}`) | Company name |
| `{{company_website}}` (or `{{website}}`) | Company website |
| `{{industry}}`, `{{location}}` | From the company record |
| `{{personalization}}` | The lead's personalisation sentence, or the company's AI hook |
| `{{sender_name}}`, `{{sender_first_name}}` | The sending inbox's display name |

**Fallbacks.** `{{first_name|there}}` uses "there" when a lead has no first name.

- **No fallback:** without one, a lead missing that value is **skipped** rather than sent "Hi ,". You'll see `missing_variable:first_name` as the stop reason.
- **Typos:** misspelled variables are rejected when you save.
- **Preview:** the **Email preview** card on a campaign's page shows any step rendered for a real lead, and flags leads who'd be skipped.

Editing a sequence while campaigns use it is fine. Leads keep their place, and upcoming steps use the new text. A sequence can't be deleted while an active or paused campaign uses it.

## Campaigns

A campaign sends one sequence to a set of leads, from a pool of inboxes, on a schedule.

### Creating one

**Campaigns → New Campaign**, then set:

- **Name** and **sequence**.
- **Sending hours and time zone**: emails only go out between the start and end time, in this time zone. It defaults to your browser's time zone, and the form shows what the window is in your own time.
- **Pause between emails** (default 2–5 minutes): after each email, the campaign waits a random time in this range before the next, so sends trickle out in breaks instead of all at once. Set both to 0 for no pause.
- **Send on weekends** and **stop sequence when a lead replies**.

### The campaign page

Everything for one campaign is on one page:

- **Status banner** (while active): what the campaign is doing and when the next email goes out:
  - *Sending now*
  - *On a break* (next email around 3:42 PM)
  - *Outside sending hours* (resumes around 9:00 PM)
  - *Inbox limits reached*
  - *Waiting on follow-ups*
- **Before this campaign can send**: a checklist of anything missing (sequence, inboxes, leads, OpenAI key, bad variables).
- **Recipients**: add an uploaded lead list, all prospects, or upload a new CSV straight into the campaign. Duplicates and uncontactable prospects are skipped automatically.
- **Sending inboxes**: tick which connected inboxes this campaign sends from. Each lead stays with the same inbox for every step, so follow-ups thread correctly.
- **Email preview**: any step rendered for one of the campaign's leads, exactly as it will be sent. Click **Another lead** to cycle through them; it also warns you about leads who'd be skipped for a missing variable.
- **Leads table**: 30 per page. It shows each lead's status, emails sent, next send time, and why they stopped (replied, bounced, …). The **–** button removes a lead from the campaign; emails already sent stay in history.
- **Campaign Settings → Edit**: change anything above. A shorter pause takes effect immediately. The sequence can only be changed while the campaign is paused.

**Start sending** activates the campaign, and its first email goes out within about a minute, if it's inside sending hours. Use **Pause** / **Resume** to stop and continue; leads keep their place. Leads added to a running campaign start the sequence automatically. A campaign marks itself **completed** when every lead has finished or stopped.

### How fast does it send?

Four limits apply, and the slowest one wins:

1. **Sending hours**: nothing goes out outside the window.
2. **The campaign's pause**: one email, then a random break (default 2–5 min).
3. **Each inbox's daily limit**: shared with warmup and other campaigns.
4. **Each inbox's own minimum gap**: 30–90 seconds between its sends.

Example: a 9:00–17:00 window with a 2–5 minute pause allows roughly 100–200 emails a day per campaign, if the inboxes' daily limits allow it.

## Lead Box and the reply agent

The home page. It's a three-column inbox for your leads' replies.

- **Top: summary cards**: lead replies in the last 30 days, drafts waiting, interested leads, and your 7-day reply rate.
- **Left: Leads**: every conversation where a known prospect wrote back to any connected inbox in the last 30 days. Warmup traffic and non-prospects are filtered out.
  - **Badges:** each conversation shows the agent's category (Interested, Question, Not interested, Out of office, Unsubscribe, Wrong person) and **Draft ready** when there's a draft to approve.
  - **Search and filter:** by category, or show only drafts waiting.
- **Middle: Conversation**: the full thread. Mark the lead as converted, unsubscribed or do-not-contact, or write your own reply. Replies thread properly in the lead's mail client too.
- **Right: Agent**: the reply agent for the selected conversation.

When a lead's reply shows up here, their campaign follow-ups stop straight away.

### The reply agent

The agent reads each new lead reply, sorts it into a category, writes a one-line summary, may suggest a status change, and drafts a response. **It never sends anything itself.** Every draft waits for you to edit, then click **Approve & send** or **Dismiss**.

- **Draft reply with agent**: drafts for the open conversation. Type guidance first if you want ("shorter", "offer Thursday 2pm"), and use **Redraft** to try again.
- **Auto-draft new replies** (switch): checks for new replies every 5 minutes and drafts them in the background. **Draft all new replies now** runs it immediately.
- **Instructions** (gear icon): what the agent should know for every draft, such as your offer, prices it may quote, the next step to propose (e.g. a booking link) and tone.
- **Placeholders**: when a reply needs a fact the agent doesn't have, it writes `[[like this]]`. Sending is blocked until you fill those in.
- **Email alerts** (gear icon): enter your address to get one email whenever background drafts are waiting. It lists each lead, the summary and the full draft, with a link straight to the conversation. Alerts are sent from your first connected inbox (shown under the field). **Send test** checks it.

Conversations where you already sent the last message are skipped, and so are leads marked unsubscribed or do-not-contact. Out-of-office and unsubscribe replies get no draft, just **Mark handled**.

## Personalizer

For one-off, fully AI-written emails rather than templates. Describe your offer and upload a list of companies.

For each company, it crawls their website **live**, searches the web for recent mentions, and drafts a short email that references something specific and real. If it finds nothing specific, it keeps the email short rather than inventing details. It runs in the background, handles up to 200 leads per run, and results download as CSV.

## Analytics

Emails sent, replies and reply rate over the last 7 days, average inbox health, a 14-day sending volume chart, and per-inbox performance (sent, replies, reply rate, bounces, health).

## Book a Call and Calendar

**Book a Call** embeds your Calendly booking page. Paste your Calendly link (open the event type in Calendly → **Copy link**).

- **Book for a prospect:** search a lead, and the booking form fills in their name and email.
- **Share:** copy or open the link.
- **Reply agent:** the link is given to the agent, so drafts that propose a call include it.
- **Lead Box:** reply boxes get an **Insert booking link** button.

**Calendar** shows your booked Calendly calls in a month view. Each invitee is matched to their prospect and campaign. You can open a call's join link, reschedule or cancel it, or **Mark converted**.

To connect, create a Calendly **personal access token** under Integrations → API & Webhooks → **Generate new token**. Tick these read-only scopes:

- `users:read`, to identify your account
- `scheduled_events:read`, to read your booked calls and invitees

A token created without them fails with a "missing permission" message naming the scope to add. The token stays in your local database. If you hadn't set a booking link yet, connecting fills it in from your account.
