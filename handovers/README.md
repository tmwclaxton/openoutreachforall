# Session handovers

One file per feature. Each new session should read this index first, then the
feature files relevant to the work. Update the matching file when you change a
feature; add a new file for a new feature. Keep these **status-oriented** (what's
done / pending / how to test) — architecture lives in `CLAUDE.md` / `ARCHITECTURE.md`.

## What this is
A functionally-complete **HeyReach-style LinkedIn outreach tool**, built on a fork of
`eracle/OpenOutreach` (Django + Django admin + a single-page dashboard at `/dashboard/`).
Branding: "Grantgunner". Drives a real LinkedIn account via `linkedin_cli` (Playwright + Voyager).

## Where it runs
- **Dev / source of truth:** this repo on **asus-fedora** at `~/OpenOutreach`, branch `feat/dashboard-spa`.
  - `origin` = `github.com/archie-prog/OpenOutreach` (⚠️ **public fork** of eracle — Archie OK with this "for now", plans a private repo later). `upstream` = `eracle/OpenOutreach`.
- **Live:** **badlaptop** = `fedora-badlaptop` (tailnet `100.79.139.20`), ssh user **`linkedinautomation`**.
  - Rootless **podman**: `oo-web` (runserver `0.0.0.0:8000`) + `oo-worker` (`manage.py run_worker` loop).
  - Repo mounted `-v $REPO:/app:z` (**always `:z`, never `:Z`**), data volume `openoutreach-data:/app/data`.
  - Dashboard: **http://100.79.139.20:8000/dashboard/** — login **`archie` / `Grantgunner2026`**.

## Deploy (no CI; manual)
```
# on asus (~/OpenOutreach)
git add -A && git commit -m "..." && git push origin feat/dashboard-spa
# on badlaptop
ssh linkedinautomation@fedora-badlaptop 'cd ~/OpenOutreach && git pull --ff-only origin feat/dashboard-spa \
  && podman exec oo-web python manage.py migrate linkedin   # only if models changed \
  && podman restart oo-web                                   # + oo-worker if executor/poller/worker changed'
```
Template/JS-only change → restart `oo-web` only. Backend/poller/executor change → restart both.

## Tests (dev image `openoutreach-dev`)
```
podman run --rm -v "$PWD":/app:z --userns=keep-id --user $(id -u):$(id -g) \
  -e FASTEMBED_CACHE_DIR=/tmp/fe -e DJANGO_SETTINGS_MODULE=linkedin.django_settings \
  --entrypoint python openoutreach-dev -m pytest tests/ -q
```
Current: **353 passing, 9 skipped**. JS sanity: extract the `<script>` from `dashboard.html` and `node --check`.

## Authorised test contacts only
Live LinkedIn account `aawilding@gmail.com`. Only message/connect-test the named associates: **Toby Claxton, Joshua Young, Jess McAllister**. Everyone else is real outreach — read-only when debugging.

## Feature index & status
| Feature | File | Status |
|---|---|---|
| Slack reply notifications | [slack-notifications.md](slack-notifications.md) | ⚠️ **Code shipped — needs Archie to create the Slack webhook** |
| Flow / sequence builder | [flow-builder.md](flow-builder.md) | ✅ Live · ⏳ drag-and-drop requested (not built) |
| Accounts + send scheduling + pacing | [accounts-and-scheduling.md](accounts-and-scheduling.md) | ✅ Live |
| Dashboard analytics | [dashboard-analytics.md](dashboard-analytics.md) | ✅ Live |
| Leads + AI lead finder + AI chat log | [leads-and-ai-chat.md](leads-and-ai-chat.md) | ✅ Live |
| Campaigns (native) + contact-once dedup | [campaigns.md](campaigns.md) | ✅ Live |
| Unibox (messaging inbox) | [unibox.md](unibox.md) | ✅ Live |
| AI settings (own API key) | [ai-settings.md](ai-settings.md) | ✅ Live |
