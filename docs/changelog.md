# Changelog

## Native TOTP 2FA (2026-06-08)
- `LinkedInProfile.totp_secret` (base32 Google Authenticator secret). `linkedin/auth/totp.py` generates the current 6-digit code via native RFC 6238 (no dependency, verified against the RFC test vector).
- `linkedin/auth/login.py`: when a profile has a `totp_secret`, login drives the form itself and **auto-fills the 2FA code** instead of waiting for a human; `launch.py` routes to it. Falls back to `linkedin_cli.authenticate` (human-in-the-loop) when no secret is set.
- Tests: `tests/auth/test_totp.py`.

## M6 — Per-account daily caps + round-robin (2026-06-08)
- `LinkedInProfile.daily_caps_json` (default 25 connect / 50 message / 5 inmail / 100 profile_visit·like_post / 50 follow_up) + `last_used_at`; `AccountDailyCounter` (per account/day/action, increment-only, never deleted).
- `linkedin/accounts/limits.py`: `has_capacity`/`record_action`/`select_account` — least-recently-used account in a campaign's pool with remaining headroom, else None (defer).
- Executor enforces caps: defers a state to tomorrow when the account is at its cap for the step's action, and records every action in the counter. Admin: per-account **daily-usage** page (today vs cap + 30-day history) + counter list.
- Tests: `tests/db/test_daily_counter.py`, `tests/tasks/test_account_rotation.py` (cap-then-defer; 10 leads round-robin 5/5 across two accounts).

## M5 — Unified inbox (2026-06-08)
- `MessageThreadAdmin` becomes the inbox: filter by account / unread / has-reply / lead source, search by lead + message body, sorted by most-recent message, conversation shown via message inline.
- **Privacy default** (`ToolScopeFilter`): only threads this tool messaged into (`sent_via_tool` outbound) are shown unless `scope=all` is chosen.
- Actions: **Mark read** (sets `read_at`) + per-thread `mark-read/` endpoint; **Pause campaign for these leads** (sets active `LeadCampaignState` → `paused_manual`). No hard-delete.
- Tests: `tests/admin/test_inbox_views.py` (load, privacy default + scope=all, unread filter, mark-read, pause).

## M4 — InMail action (2026-06-08)
- `linkedin/actions/inmail.py`: `send_inmail(session, lead, subject, body)` → `{success, skipped, error, linkedin_message_id}`. App-side Playwright composer (`_compose_inmail`, mocked in tests) — no `linkedin_cli` InMail primitive exists.
- Gated by `LinkedInProfile.has_inmail` (Sales Nav/Recruiter): no capability → **skips cleanly**, sequence continues, no crash. UI failures are captured, not raised.
- Un-stubs M2's InMail step (executor now calls the real action and only logs on success). Tests: `tests/actions/test_inmail.py` (skip path, success, UI-failure-no-crash, in-sequence skip).

## M3 — Reply detection (2026-06-08)
- `MessageThread` + `Message` (direction in/out, idempotent by `linkedin_message_id`, `read_at`/`sent_via_tool` for the M5 inbox).
- `linkedin/inbox/poller.py`: polls active sequence leads' conversations, persists messages, and sets `LeadCampaignState` → `stopped_reply` when an inbound reply arrives after the lead's last action — so a lead who answered is never messaged again. `fetch_thread_messages` is the single mockable boundary over `linkedin_cli`.
- `manage.py run_reply_poller` + daemon hook + admin (thread/message viewers, no hard-delete). Direction/id inferred heuristically (linkedin_cli's `get_conversation` drops urn/id) — flagged for the cli fork.
- Tests: `tests/tasks/test_reply_poller.py`, `tests/db/test_message_models.py`.

## M2 — Sequence engine (2026-06-08)
- `Sequence` + `SequenceStep` (branching tree: `root`/`success`/`failure`, step types connect/message/inmail/wait/profile_visit/like_post) + `LeadCampaignState` (executor cursor); `Campaign` extended with `sequence`/`lead_list`/`status`.
- `linkedin/sequences/executor.py`: enrolls lead lists, advances each state through the tree, two-phase connect (send → wait → accepted?→success / not-accepted→failure), message→no-reply branch, InMail-on-failure; browser actions isolated behind mockable wrappers.
- Coexists with AI-discovery (only `sequence`-driven campaigns are executed); `manage.py run_sequences` + daemon hook + admin (Sequence w/ step inline, Campaign activate+enroll action, LeadCampaignState viewer); no hard-delete.
- InMail send is stubbed pending M4. Tests: `tests/db/test_sequence_models.py`, `tests/db/test_lead_campaign_state.py`, `tests/tasks/test_sequence_executor.py`.

## M1 — Manual lead import (2026-06-07)
- New `LeadList` model (`linkedin/models.py`): named lead collections; **soft-delete only** via `archived_at` + `archive()`.
- `Lead.lead_list` FK (nullable, `SET_NULL`) links leads to a list without disturbing the AI-discovery path.
- `linkedin/leads/importer.py`: CSV import (dedup by `public_identifier`) and people-search-URL scrape+enrich (1000 cap, idempotent).
- `manage.py leadlist_import` command + Django admin (LeadList list/detail, CSV upload form, Lead enrichment-status filter); no hard-delete exposed.
- Tests: `tests/db/test_lead_list.py`, `tests/api/test_search_scrape.py`, `tests/admin/test_lead_list_views.py`.
