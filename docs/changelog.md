# Changelog

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
