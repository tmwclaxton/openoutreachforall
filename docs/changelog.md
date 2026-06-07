# Changelog

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
