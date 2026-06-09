# Slack reply notifications

**Status: ⚠️ Code shipped & deployed — BLOCKED on Archie creating the Slack webhook.**

## What Archie wants (final, agreed)
A **one-way notification** only (the two-way "Slack channel chat room" idea was **put on a pin** — see bottom). When **any lead on any account replies**, post to a Slack channel: **who replied + their message + a View-on-LinkedIn link**. It's just a prompt for Archie to go reply in LinkedIn himself. The Slack workspace/channel must be **separate from CPAK's** Slack.

## What's built (live)
- `SiteConfig.slack_webhook_url` + `SiteConfig.slack_notify_replies` (DB-stored, editable in dashboard).
- `linkedin/notify/slack.py` — `post_text()` (POSTs to the Incoming Webhook via stdlib urllib, swallows errors) and `notify_reply(name, message, lead_url, account)`.
- Poller (`linkedin/inbox/poller.py`): on a **genuinely new inbound reply** (newly-created Message, post-dates our last action, thread `contacted_by_tool`) calls `_notify_reply(...)`. One ping per new reply; never raises into the poll loop.
- Dashboard **AI Context tab → "Slack notifications"**: enable toggle, webhook URL field, **Save**, **Send test** (`api/slack/test/`).
- Verified with a mocked HTTP post: gates on config, formats `:speech_balloon: *New LinkedIn reply from <name>* > <message> <url|View on LinkedIn> · via <account>`.

## ⏳ PENDING — Archie's action to switch it on
1. `api.slack.com/apps → Create New App → From scratch` in the **new (non-CPAK) workspace**.
2. **Incoming Webhooks → On → Add New Webhook to Workspace →** pick the channel → copy URL.
3. Dashboard → AI Context → Slack notifications → tick "Notify me", paste URL, **Save**, **Send test**.

Until the webhook URL is saved, notifications are inert (no error).

## Pinned (deferred) — two-way "chat room"
Replying *from Slack* back to the LinkedIn lead was discussed (CPAK does per-order channels via a **bot token**, polling `conversations.history`). Decided **not** to build for now — Archie only wants the notification prompt. If revisited: needs a Slack **bot token** app (scopes `chat:write`, `channels:history/read`, maybe `channels:manage`), a lead→Slack-thread mapping, and the worker polling Slack to relay replies into the existing manual-send path (`Message.pending_send`). Design choice still open: one channel + thread-per-lead (recommended) vs channel-per-lead.

## Key files
`linkedin/notify/slack.py`, `linkedin/inbox/poller.py` (`_notify_reply`), `linkedin/models.py` (SiteConfig slack_*), `linkedin/dashboard/views.py` (`api_ai_config*`, `api_slack_test`), `dashboard.html` (Slack section + `testSlack`/`saveAiConfig`). Migration `0027`.
