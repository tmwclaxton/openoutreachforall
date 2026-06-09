# Leads + AI lead finder + AI chat log

**Status: ✅ Live.**

## What it does (Leads tab)
Three import cards in a 2-col grid (CSV top-left, Find-with-AI below-left, LinkedIn search spanning right),
then a full-width Lead lists table.
- **CSV import** (dedup by public_identifier).
- **LinkedIn search** — advanced filters (keywords/name/title/company/school/degree/language) build a search URL, or paste a URL. Queued; the worker scrapes + enriches.
- **Find with AI** — describe ICP → LLM generates search keywords → worker searches + enriches.
- Per list: **target count** (worker fills toward it across cycles), **Continue / refine** (append a new prompt and/or raise target), **Export CSV** (name/title/company/location/ai_score/reason/url), **💬 AI chat**, **Add to campaign**.

## AI chat log
`LeadListEvent` (append-only) records the thread: user prompts/refinements + each finder run's keywords & leads-added. `api/leadlist/<id>/events/`. Legacy lists with no events **reconstruct** the prompt from `source_url` (split on `" | "`) + a status line, so the thread is never blank.

## AI lead scoring
`linkedin/ml/lead_score.py` scores each lead 0–100 for fit vs `SiteConfig.ai_context`. Worker runs `score_pending_leads`; `backfill_lead_profiles` re-scrapes title/company/location then re-scores.

## Notes
- "Continue/refine" appends the prompt to `source_url` joined by `" | "` — **AI lists only**. For `search_url` lists, `source_url` is a real URL; a text refine would corrupt it (only raising the target is safe there). Flagged, not yet guarded.
- A list goes idle (pending_search=False) when a pass adds 0 (search exhausted) — Continue/refine restarts it.

## Key files
`linkedin/leads/importer.py` (import_csv/search/ai, log_event, process_pending_searches, backfill),
`linkedin/ml/lead_score.py`, `linkedin/ml/search_keywords.py`, `crm/models/lead.py`,
`views.py` (`api_leads*`, `api_leadlist_events`, `api_leadlist_export`), `dashboard.html` (Leads tab + AI chat modal). Migrations `0021` (target_count), `0022` (LeadListEvent).
