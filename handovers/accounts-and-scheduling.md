# Accounts + send scheduling + pacing

**Status: ✅ Live.**

## What it does (Accounts tab)
Add/manage LinkedIn accounts; per-account daily caps + a full send schedule.

### Daily caps (M6)
`LinkedInProfile.daily_caps_json` per action; `AccountDailyCounter` tallies; `has_capacity`/`record_action`.
Connect default 25. **Advisory banner** appears if connect/day (or random max) > **30** — "for safe use we don't recommend over 30/day".

### Randomised connect cap (🎲)
Per account: `connect_random_enabled` + `connect_random_min`/`max` (default 19–25). When on, the day's
connect cap is picked randomly in range, **stable per (account, day)** via a deterministic seed
(`account.pk*1e6 + date.toordinal()`) — survives worker restarts, varies day to day. UI shows "today N".

### Per-account send window
`send_start_hour`/`send_end_hour` (default 9–17), `send_timezone` (IANA **dropdown**, default Europe/London),
`send_weekdays` (default Mon–Fri), `skip_bank_holidays` + `holiday_country` (**dropdown** from the `holidays`
lib's supported countries; friendly names). Sends only inside this local window/weekdays, skipping bank holidays.

### Paced "drip" — schedule-anchored (catches up)
`limits.next_action_at(account, action)` pegs send #N of the day to `window_open + N*spacing`
(spacing = window/cap), with jitter — NOT to the last send. So it spreads the cap evenly across the window
**and self-corrects**: if it falls behind (slow cycle, restart, stall) it catches up toward the cap instead
of drifting; a `min_gap` floor (0.4×spacing) keeps catch-up a steady recovery, never an instant burst. Never
sends outside the window. Gated by `conf.ENABLE_ACTION_PACING` (**True** in prod, off in tests via conftest).
(Earlier last-action-chained pacing couldn't recover lost time — after a morning stall it just plodded at
1/spacing and undershot the daily cap. Fixed 2026-06-09.)

## Wait steps = next working day, random time
`limits.random_slot_in_working_days(account, days)` — "Wait N days" resolves to **N working days ahead**
(skipping non-working weekdays + bank holidays), at a **random time within the send window** (not exact 24h).
Used by `executor._handle_wait`. So "wait 1 day" from a Friday → a random in-window time on Monday.

## Worker loop cadence (why pacing was firing too slowly)
The worker (`run_worker.py`) must run the **sender (`run_due_states`) first and every cycle**, or paced actions wait behind slow work. Bug found 2026-06-09: `poll_replies` re-scraped *every* lead's conversation each cycle (~30 min/cycle), so only ~1 connect fired per 30 min → ~5/day. Fixed: sender runs first every cycle; `poll_replies(limit=12)` is bounded (ordered by most-recent activity, rotates coverage); heavy work (`process_pending_searches`/`backfill`/`score`) runs every ~10 min (`HEAVY_EVERY`). Keep the sender unblocked — don't put slow per-lead scraping ahead of it.

## Gotchas / notes
- `holidays` is **pip-installed into the live containers** at runtime AND in `requirements/base.txt`. If a container is rebuilt from an old image without rebuilding, bank-holiday skipping goes inert (degrades gracefully). A proper image rebuild bakes it in.
- Manual Unibox sends are **not** window-gated (user-initiated). Only the automated executor respects the window/pacing.

## Key files
`linkedin/accounts/limits.py` (cap_for/random, is_send_time/next_send_time, next_action_at, pacing),
`linkedin/conf.py` (`ENABLE_ACTION_PACING`), `linkedin/sequences/executor.py` (pacing gate + `_defer_until`),
`linkedin/models.py` (LinkedInProfile send_* / connect_random_*), `views.py` (`api_accounts`, `api_account_update`, `api_holiday_countries`), `dashboard.html` (accounts table + schedule row), `tests/test_send_schedule.py`. Migrations `0025`/`0026`.
