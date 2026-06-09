# Dashboard analytics

**Status: ✅ Live.**

## What it does (Dashboard tab)
- Filter bar: **Period** (All / 7 / 30 / 90 days / 12 months), **Campaign**, **Account**.
- KPI tiles: Connection Requests, Messages Sent, InMails Sent, Replies, Active, Completed.
- **HeyReach-style time-series chart** (Chart.js via CDN): connections / messages / inmails / replies per
  day→week→month (granularity auto-picks from the period), smooth multi-line area, filtered by all three filters.

## Notes
- Chart.js loads from CDN → the **browser** needs internet (fine over Tailscale). Not self-hosted; offer to vendor locally if ever needed.
- Replies KPI = MessageThreads with an inbound message (not "stopped" states).
- Backend filters: actions by `ActionLog.linkedin_profile_id`/`campaign_id`/`created_at`; replies by thread account/campaign.

## Key files
`linkedin/dashboard/views.py` (`api_kpis`, `api_kpi_timeseries`), `dashboard.html` (filter bar, `dashQuery`, `drawChart`, `loadDash`). No migration.
