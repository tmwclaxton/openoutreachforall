# Unibox (messaging inbox)

**Status: ✅ Live.**

## What it does (Unibox tab)
A normal messaging app: thread list → full conversation. Bold-if-unread, account badge,
**View on LinkedIn** link, manual send **from the thread's owning account** (queued via `Message.pending_send`,
sent by the worker). Filters: **Account**, **Campaign**, **Lead list**, and **Show** (Replied / Sent-no-reply / All).

## "Only people we contacted" gate (important)
`MessageThread.contacted_by_tool` — the Unibox **only shows threads THIS tool started**, never the
account's pre-existing conversations from other tools (the account had old HeyReach threads that the
poller had scraped). Set True when the executor messages/InMails a lead (`_mark_contacted`) or on a manual
Unibox send; the poller **self-heals** old threads by setting it when an outbound message is dated at/after
the lead's enrolment (`state.created_at`). Verified: only Toby + Josh show; ~81 old HeyReach threads hidden.

## Reply detection
`poll_replies` (M3): persists conversation messages, flips a lead to `stopped_reply` when an inbound
message post-dates our last action ("if they replied, stop messaging"). Also where the **Slack notify**
fires (see slack-notifications.md).

## Key files
`linkedin/inbox/poller.py` (poll_replies, process_pending_sends, _notify_reply), `linkedin/models.py`
(MessageThread/Message), `views.py` (`api_inbox_threads/thread/send/accounts`), `dashboard.html` (Unibox tab). Migration `0024` (contacted_by_tool).
