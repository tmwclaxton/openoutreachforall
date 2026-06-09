# Dashboard analytics

**Status: ✅ Live.**

## What it does (Dashboard tab)
- Filter bar: **Period** (All / 7 / 30 / 90 days / 12 months), **Campaign**, **Account**.
- KPI tiles: Connection Requests, **Connections Accepted**, Messages Sent, InMails Sent, **Posts Liked**, Replies, Active, Completed.
- **Activity feed** (`api/activity/`) with a type filter (All / accepted / likes / messages / connects / inmails), respecting the period/campaign/account filters — shows action + **lead name** + time + account. Acceptances are recorded as an `ActionLog` `connect_accepted` event when the executor detects a connection was accepted; `ActionLog.lead` now ties every action to who it was for. Everything here is the tool's own outreach only (ActionLog is written solely by the executor).
- **HeyReach-style time-series chart** (Chart.js via CDN): connections / messages / inmails / replies per
  day→week→month (granularity auto-picks from the period), smooth multi-line area, filtered by all three filters.

## Notes
- Chart.js loads from CDN → the **browser** needs internet (fine over Tailscale). Not self-hosted; offer to vendor locally if ever needed.
- Replies KPI = MessageThreads with an inbound message (not "stopped" states).
- Backend filters: actions by `ActionLog.linkedin_profile_id`/`campaign_id`/`created_at`; replies by thread account/campaign.

## Key files
`linkedin/dashboard/views.py` (`api_kpis`, `api_kpi_timeseries`), `dashboard.html` (filter bar, `dashQuery`, `drawChart`, `loadDash`). No migration.
