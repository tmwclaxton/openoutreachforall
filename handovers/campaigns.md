# Campaigns (native) + contact-once dedup

**Status: ✅ Live.**

## What it does (Campaigns tab) — no Django admin
- **Create campaign** natively: name + sequence + optional lead list; launch active.
- Per-campaign **Pause / Activate / Archive** (status pills). Pause sets active lead states → `paused_manual`; Activate resumes them (due now) + enrolls new leads; Archive = soft (terminal, hidden).
- **Add leads** — attach any lead list to a campaign (a campaign can accumulate from several lists).
- **Leads** view per campaign: stage + AI score, sortable/filterable by state.
- Worker auto-enrolls active campaigns each cycle (`enroll_active_campaigns`) so lists still filling get picked up.

## Contact-once dedup (important)
A person is enrolled **at most once across ALL campaigns**. `executor.contacted_lead_ids(exclude_campaign)`
excludes any lead already enrolled in any other campaign (**any state, ever**) — so someone resurfacing in a
new search/list is never double-contacted. (Lead rows are unique per person via public_identifier dedup at import.)
NB: this guards **future** enrolments; pre-existing duplicate enrolments from before this shipped still exist
(e.g. some leads are in both "GrantGunner Investors …" campaigns).

## Key files
`linkedin/sequences/executor.py` (`enroll_leads`/`enroll_campaign`/`enroll_lead_list`/`enroll_active_campaigns`, `busy_lead_ids`, `contacted_lead_ids`), `linkedin/models.py` (Campaign, LeadCampaignState), `views.py` (`api_campaigns`, `api_campaign_create/update/add_leads/leads`), `linkedin/management/commands/run_worker.py`, `dashboard.html` (Campaigns tab).
