# Changelog

## M1 — Manual lead import (2026-06-07)
- New `LeadList` model (`linkedin/models.py`): named lead collections; **soft-delete only** via `archived_at` + `archive()`.
- `Lead.lead_list` FK (nullable, `SET_NULL`) links leads to a list without disturbing the AI-discovery path.
- `linkedin/leads/importer.py`: CSV import (dedup by `public_identifier`) and people-search-URL scrape+enrich (1000 cap, idempotent).
- `manage.py leadlist_import` command + Django admin (LeadList list/detail, CSV upload form, Lead enrichment-status filter); no hard-delete exposed.
- Tests: `tests/db/test_lead_list.py`, `tests/api/test_search_scrape.py`, `tests/admin/test_lead_list_views.py`.
