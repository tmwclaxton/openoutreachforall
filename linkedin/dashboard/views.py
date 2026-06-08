# linkedin/dashboard/views.py
"""Dashboard JSON API + page (the visual layer, v1).

KPI tiles, a senders table with live cap usage, and a sequence rendered as a
branching flow graph — the HeyReach-style surfaces, served as JSON to a
self-contained page (no SPA build pipeline).
"""
from __future__ import annotations

import csv as _csv
import json
from urllib.parse import quote

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@staff_member_required
def dashboard_page(request):
    return render(request, "dashboard/dashboard.html", {})


@staff_member_required
def api_kpi_timeseries(request):
    """Per-bucket counts (connections/messages/inmails/replies) for the chart.
    Granularity: day (<=45d window), week (<=180d), else month."""
    from datetime import timedelta

    from django.db.models import Count
    from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
    from django.utils import timezone

    from linkedin.models import ActionLog, Message

    days = int(request.GET.get("days") or 30)
    campaign = request.GET.get("campaign") or None
    window = days if days else 365
    if window <= 45:
        gran, trunc = "day", TruncDay
    elif window <= 180:
        gran, trunc = "week", TruncWeek
    else:
        gran, trunc = "month", TruncMonth
    start = timezone.now() - timedelta(days=window)

    def series(qs, ts_field):
        qs = qs.filter(**{f"{ts_field}__gte": start})
        rows = qs.annotate(b=trunc(ts_field)).values("b").annotate(c=Count("id"))
        return {r["b"].date().isoformat(): r["c"] for r in rows if r["b"]}

    base = ActionLog.objects.all()
    if campaign:
        base = base.filter(campaign_id=campaign)
    connects = series(base.filter(action_type="connect"), "created_at")
    messages = series(base.filter(action_type="message"), "created_at")
    inmails = series(base.filter(action_type="inmail"), "created_at")
    rep_qs = Message.objects.filter(direction="in")
    if campaign:
        rep_qs = rep_qs.filter(thread__lead__campaign_states__campaign_id=campaign)
    replies = series(rep_qs, "sent_at")

    labels = sorted(set(connects) | set(messages) | set(inmails) | set(replies))
    return JsonResponse({
        "granularity": gran,
        "labels": labels,
        "connections": [connects.get(d, 0) for d in labels],
        "messages": [messages.get(d, 0) for d in labels],
        "inmails": [inmails.get(d, 0) for d in labels],
        "replies": [replies.get(d, 0) for d in labels],
    })


@staff_member_required
def api_context(request):
    from linkedin.models import SiteConfig

    return JsonResponse({"ai_context": SiteConfig.load().ai_context})


@csrf_exempt
@staff_member_required
@require_POST
def api_context_save(request):
    from linkedin.models import SiteConfig

    payload = json.loads(request.body or "{}")
    cfg = SiteConfig.load()
    cfg.ai_context = (payload.get("ai_context") or "")[:10000]
    cfg.save(update_fields=["ai_context"])
    return JsonResponse({"ok": True})


@csrf_exempt
@staff_member_required
@require_POST
def api_update_step(request, step_id):
    """Edit a sequence step: change its config, and/or change what the step
    actually IS (its ``step_type``). Changing type resets the config to that
    type's defaults (unless a config is supplied)."""
    from linkedin.models import SequenceStep

    step = SequenceStep.objects.filter(pk=step_id).first()
    if not step:
        return JsonResponse({"error": "not found"}, status=404)
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "bad json"}, status=400)

    new_type = payload.get("step_type")
    new_config = payload.get("config")
    if new_type is None and not isinstance(new_config, dict):
        return JsonResponse({"error": "config must be an object"}, status=400)

    fields = []
    if new_type is not None:
        if new_type not in SequenceStep.StepType.values:
            return JsonResponse({"error": "bad step_type"}, status=400)
        # Branch-arity safety: only connect/message carry a 'no' (failure) branch.
        # Refuse a change that would orphan an existing failure branch.
        branching = {SequenceStep.StepType.CONNECT, SequenceStep.StepType.MESSAGE}
        if new_type not in branching and step.children.filter(branch=SequenceStep.Branch.FAILURE).exists():
            return JsonResponse(
                {"error": "This step has a 'No reply / Not accepted' branch. Change it to "
                          "Send message or Send connection request, or remove that branch first."},
                status=400,
            )
        if new_type == SequenceStep.StepType.END and step.children.exists():
            return JsonResponse({"error": "End can't have steps after it — remove them first."}, status=400)
        step.step_type = new_type
        fields.append("step_type")
        if not isinstance(new_config, dict):
            step.config = dict(_STEP_DEFAULTS.get(new_type, {}))
            fields.append("config")

    if isinstance(new_config, dict):
        step.config = new_config
        fields.append("config")

    step.save(update_fields=fields)
    return JsonResponse({"ok": True, "step_type": step.step_type, "config": step.config})


def _lead_name(lead):
    if lead.first_name and lead.last_name:
        return f"{lead.first_name} {lead.last_name}".strip()
    parts = (lead.public_identifier or "").split("-")
    # Drop a trailing LinkedIn hash suffix (pure digits, or mixed letters+digits).
    while parts and (parts[-1].isdigit() or (any(c.isdigit() for c in parts[-1]) and any(c.isalpha() for c in parts[-1]))):
        parts.pop()
    derived = " ".join(p.title() for p in parts)
    return derived or lead.first_name or "Lead"


@staff_member_required
def api_accounts(request):
    from linkedin.accounts.limits import daily_count, inmail_sent_this_month
    from linkedin.models import LinkedInProfile

    out = []
    for a in LinkedInProfile.objects.all():
        caps = a.daily_caps_json or {}
        out.append({
            "id": a.pk, "username": a.linkedin_username, "active": a.active,
            "has_inmail": a.has_inmail, "has_totp": bool(a.totp_secret),
            "inmail_monthly_cap": a.inmail_monthly_cap, "inmail_used_month": inmail_sent_this_month(a),
            "connect_cap": caps.get("connect", 25), "message_cap": caps.get("message", 50),
            "connect_used": daily_count(a, "connect"), "message_used": daily_count(a, "message"),
        })
    return JsonResponse({"accounts": out})


@csrf_exempt
@staff_member_required
@require_POST
def api_account_add(request):
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    payload = json.loads(request.body or "{}")
    email = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not email or not password:
        return JsonResponse({"error": "email + password required"}, status=400)
    handle = (email.split("@")[0].lower().replace(".", "_").replace("+", "_") or "acct")[:140]
    base, i = handle, 1
    while User.objects.filter(username=handle).exists():
        handle = f"{base}{i}"
        i += 1
    user = User.objects.create(username=handle, is_staff=True, is_active=True)
    user.set_unusable_password()
    user.save()
    prof = LinkedInProfile.objects.create(
        user=user, linkedin_username=email, linkedin_password=password,
        has_inmail=bool(payload.get("has_inmail")), totp_secret=payload.get("totp_secret", "") or "",
        legal_accepted=True,
    )
    return JsonResponse({"ok": True, "id": prof.pk})


@csrf_exempt
@staff_member_required
@require_POST
def api_account_update(request, account_id):
    from linkedin.models import LinkedInProfile

    prof = LinkedInProfile.objects.filter(pk=account_id).first()
    if not prof:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    if "active" in payload:
        prof.active = bool(payload["active"])
    if "has_inmail" in payload:
        prof.has_inmail = bool(payload["has_inmail"])
    if payload.get("totp_secret"):
        prof.totp_secret = payload["totp_secret"]
    if payload.get("inmail_monthly_cap") is not None:
        prof.inmail_monthly_cap = int(payload["inmail_monthly_cap"])
    caps = prof.daily_caps_json or {}
    if payload.get("connect_cap") is not None:
        caps["connect"] = int(payload["connect_cap"])
    if payload.get("message_cap") is not None:
        caps["message"] = int(payload["message_cap"])
    prof.daily_caps_json = caps
    prof.save()
    return JsonResponse({"ok": True})


@staff_member_required
def api_campaigns(request):
    from linkedin.models import Campaign

    out = []
    qs = Campaign.objects.filter(sequence__isnull=False).exclude(
        status=Campaign.Status.ARCHIVED
    ).select_related("sequence", "lead_list").order_by("-id")
    for c in qs:
        out.append({
            "id": c.pk,
            "name": c.name,
            "status": c.status,
            "sequence": c.sequence.name if c.sequence else "",
            "sequence_id": c.sequence_id,
            "lead_list": c.lead_list.name if c.lead_list else "",
            "lead_list_id": c.lead_list_id,
            "leads": c.lead_states.count(),
        })
    return JsonResponse({"campaigns": out})


@csrf_exempt
@staff_member_required
@require_POST
def api_campaign_create(request):
    """Create a sequence-driven campaign natively (no Django admin): name +
    sequence + optional lead list. Launches active by default and enrolls the
    list's leads immediately."""
    from django.db import IntegrityError

    from linkedin.models import Campaign
    from linkedin.sequences.executor import enroll_campaign

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "").strip()
    sequence_id = payload.get("sequence_id")
    lead_list_id = payload.get("lead_list_id") or None
    status = payload.get("status") or Campaign.Status.ACTIVE
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    if not sequence_id:
        return JsonResponse({"error": "pick a sequence"}, status=400)
    try:
        campaign = Campaign.objects.create(
            name=name, sequence_id=sequence_id, lead_list_id=lead_list_id, status=status,
        )
    except IntegrityError:
        return JsonResponse({"error": "a campaign with that name already exists"}, status=400)
    enrolled = 0
    if status == Campaign.Status.ACTIVE and lead_list_id:
        enrolled = enroll_campaign(campaign).get("enrolled", 0)
    return JsonResponse({"ok": True, "id": campaign.pk, "enrolled": enrolled})


def _set_states(campaign, from_states, to_state, *, due_now=False):
    """Bulk-move a campaign's lead states between lifecycle states (pause/resume/
    archive). Never deletes — terminal/paused moves only."""
    from django.utils import timezone

    from linkedin.models import LeadCampaignState

    qs = LeadCampaignState.objects.filter(campaign=campaign, state__in=from_states)
    fields = {"state": to_state}
    if due_now:
        fields["next_action_due_at"] = timezone.now()
    return qs.update(**fields)


@csrf_exempt
@staff_member_required
@require_POST
def api_campaign_update(request, campaign_id):
    """Update a campaign: rename, swap sequence/list, or change status. Status
    changes drive the lead states — pause→paused_manual, activate→active (due
    now) + enroll, archive→archived (terminal). No hard deletes."""
    from linkedin.models import Campaign, LeadCampaignState
    from linkedin.sequences.executor import enroll_campaign

    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if not campaign:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    S, LS = Campaign.Status, LeadCampaignState.State

    updates = []
    if "name" in payload and payload["name"].strip():
        campaign.name = payload["name"].strip(); updates.append("name")
    if "sequence_id" in payload:
        campaign.sequence_id = payload["sequence_id"] or None; updates.append("sequence")
    if "lead_list_id" in payload:
        campaign.lead_list_id = payload["lead_list_id"] or None; updates.append("lead_list")

    status = payload.get("status")
    enrolled = 0
    if status and status != campaign.status:
        campaign.status = status; updates.append("status")
        if status == S.ACTIVE:
            _set_states(campaign, [LS.PAUSED_MANUAL], LS.ACTIVE, due_now=True)
            enrolled = enroll_campaign(campaign).get("enrolled", 0)
        elif status == S.PAUSED:
            _set_states(campaign, [LS.ACTIVE], LS.PAUSED_MANUAL)
        elif status == S.ARCHIVED:
            _set_states(campaign, [LS.ACTIVE, LS.PAUSED_MANUAL], LS.ARCHIVED)

    if updates:
        campaign.save()
    return JsonResponse({"ok": True, "status": campaign.status, "enrolled": enrolled})


@csrf_exempt
@staff_member_required
@require_POST
def api_campaign_add_leads(request, campaign_id):
    """Add a lead list's leads into this campaign (a campaign can accumulate
    leads from several lists). If the campaign has no primary list yet, adopt
    this one as it."""
    from linkedin.models import Campaign, LeadList
    from linkedin.sequences.executor import enroll_lead_list

    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if not campaign:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    ll = LeadList.objects.filter(pk=payload.get("list_id")).first()
    if not ll:
        return JsonResponse({"error": "lead list not found"}, status=404)
    if not campaign.lead_list_id:
        campaign.lead_list = ll
        campaign.save(update_fields=["lead_list"])
    result = enroll_lead_list(campaign, ll)
    return JsonResponse({"ok": True, **result})


@staff_member_required
def api_campaign_leads(request, campaign_id):
    from linkedin.models import LeadCampaignState

    states = (
        LeadCampaignState.objects.filter(campaign_id=campaign_id)
        .select_related("lead", "current_step")
        .order_by("-lead__ai_score")
    )
    leads = []
    for s in states:
        stage = s.current_step.step_type if s.current_step else "—"
        if s.current_step and s.current_step.step_type == "connect" and s.awaiting_decision:
            stage = "connect (awaiting accept)"
        leads.append({
            "lead_name": _lead_name(s.lead),
            "lead_url": s.lead.linkedin_url,
            "title": s.lead.title,
            "company": s.lead.company,
            "ai_score": s.lead.ai_score,
            "stage": stage,
            "state": s.state,
        })
    return JsonResponse({"leads": leads})


@staff_member_required
def api_inbox_accounts(request):
    from linkedin.models import LinkedInProfile

    return JsonResponse({"accounts": [
        {"id": a.pk, "name": a.linkedin_username} for a in LinkedInProfile.objects.all()
    ]})


@staff_member_required
def api_inbox_threads(request):
    from linkedin.models import MessageThread

    account = request.GET.get("account")
    # Conversations with at least one MESSAGE (excludes connection-request-only
    # threads). filter: all | replied (has inbound) | sent (outbound, no reply yet).
    f = request.GET.get("filter", "replied")
    # Only threads THIS tool actually started — never the account's pre-existing
    # LinkedIn conversations from other tools.
    base = MessageThread.objects.filter(contacted_by_tool=True, messages__isnull=False)
    if f == "replied":
        base = base.filter(messages__direction="in")
    elif f == "sent":
        base = base.filter(messages__direction="out").exclude(messages__direction="in")
    qs = (
        base.distinct().select_related("lead", "account").order_by("-last_message_at", "-created_at")
    )
    if account:
        qs = qs.filter(account_id=account)

    threads = []
    for t in qs[:300]:
        last = t.messages.order_by("-sent_at", "-fetched_at").first()
        threads.append({
            "id": t.pk,
            "lead_name": _lead_name(t.lead),
            "lead_url": t.lead.linkedin_url,
            "account_id": t.account_id,
            "account_name": t.account.linkedin_username if t.account else "",
            "last_message": (last.body[:90] if last and last.body else ""),
            "last_direction": last.direction if last else "",
            "unread": t.read_at is None,
            "has_reply": t.has_inbound_reply,
        })
    return JsonResponse({"threads": threads})


@staff_member_required
def api_inbox_thread(request, thread_id):
    from django.utils import timezone

    from linkedin.models import MessageThread

    t = MessageThread.objects.select_related("lead", "account").filter(pk=thread_id).first()
    if not t:
        return JsonResponse({"error": "not found"}, status=404)
    if t.read_at is None:
        t.read_at = timezone.now()
        t.save(update_fields=["read_at"])
    msgs = [
        {"direction": m.direction, "body": m.body, "sent_at": m.sent_at.isoformat() if m.sent_at else ""}
        for m in t.messages.order_by("sent_at", "fetched_at")
    ]
    return JsonResponse({
        "id": t.pk,
        "lead_name": _lead_name(t.lead),
        "lead_url": t.lead.linkedin_url,
        "account_name": t.account.linkedin_username if t.account else "",
        "messages": msgs,
    })


@staff_member_required
def api_leads(request):
    from linkedin.models import LeadList

    lists = []
    for ll in LeadList.objects.filter(archived_at__isnull=True).order_by("-created_at"):
        lists.append({
            "id": ll.pk, "name": ll.name, "source": ll.source_type,
            "count": ll.leads.count(), "target": ll.target_count, "pending": ll.pending_search,
        })
    return JsonResponse({"lists": lists})


@csrf_exempt
@staff_member_required
@require_POST
def api_leads_csv(request):
    from linkedin.leads import importer
    from linkedin.models import LeadList

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "CSV import").strip()
    csv_text = payload.get("csv_text") or ""
    ll = importer.create_lead_list(name=name, owner=request.user, source_type=LeadList.SourceType.CSV)
    try:
        result = importer.import_csv(ll, iter(csv_text.splitlines()))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "list_id": ll.pk, **result})


def _build_search_url(filters: dict) -> str:
    """Build a LinkedIn people-search URL from free-text filters. Entity filters
    (specific company/school/location/industry URNs) aren't resolvable without
    LinkedIn's typeahead — use a pasted URL for those.
    """
    from urllib.parse import urlencode

    params = {}
    for key in ("keywords", "firstName", "lastName", "title", "company", "school"):
        val = (filters.get(key) or "").strip()
        if val:
            params[key] = val
    network = [n for n in (filters.get("network") or []) if n in ("F", "S", "O")]
    if network:
        params["network"] = json.dumps(network, separators=(",", ":"))
    lang = (filters.get("language") or "").strip()
    if lang:
        params["profileLanguage"] = lang
    return "https://www.linkedin.com/search/results/people/?" + urlencode(params)


@csrf_exempt
@staff_member_required
@require_POST
def api_leads_search(request):
    """Queue a LinkedIn people search (filters, URL, or keyword). The browser
    worker scrapes it on its next cycle (one process owns the LinkedIn session).
    """
    from linkedin.leads import importer
    from linkedin.models import LeadList

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "Search import").strip()
    filters = payload.get("filters")
    query = (payload.get("query") or "").strip()
    if filters:
        url = _build_search_url(filters)
    elif query:
        url = query if query.startswith("http") else (
            "https://www.linkedin.com/search/results/people/?keywords=" + quote(query)
        )
    else:
        return JsonResponse({"error": "filters or query required"}, status=400)
    ll = importer.create_lead_list(
        name=name, owner=request.user, source_type=LeadList.SourceType.SEARCH_URL, source_url=url,
    )
    ll.target_count = int(payload.get("target_count") or 30)
    ll.pending_search = True
    ll.save(update_fields=["pending_search", "target_count"])
    return JsonResponse({"ok": True, "queued": True, "list_id": ll.pk})


@csrf_exempt
@staff_member_required
@require_POST
def api_leads_ai(request):
    """AI lead finder — describe your ICP; the worker generates search keywords
    via the LLM, searches, and enriches matches into a new list."""
    from linkedin.leads import importer
    from linkedin.models import LeadList

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "AI leads").strip()
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return JsonResponse({"error": "describe who you're looking for"}, status=400)
    ll = importer.create_lead_list(
        name=name, owner=request.user, source_type=LeadList.SourceType.AI, source_url=prompt[:2000],
    )
    ll.target_count = int(payload.get("target_count") or 30)
    ll.pending_search = True
    ll.save(update_fields=["pending_search", "target_count"])
    importer.log_event(ll, "user", prompt)
    importer.log_event(ll, "system", f"Target set to {ll.target_count} leads. The worker will start finding them shortly.")
    return JsonResponse({"ok": True, "queued": True, "list_id": ll.pk})


@csrf_exempt
@staff_member_required
@require_POST
def api_leads_continue(request, list_id):
    """Keep building a lead list: optionally refine the prompt ("these aren't
    right, here's why…") and/or raise the target (e.g. 1000 not 30)."""
    from linkedin.leads import importer
    from linkedin.models import LeadList

    ll = LeadList.objects.filter(pk=list_id).first()
    if not ll:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    new_prompt = (payload.get("prompt") or "").strip()
    target = payload.get("target_count")
    if new_prompt:
        ll.source_url = ((ll.source_url or "") + " | " + new_prompt)[:2000]
    if target is not None:
        ll.target_count = int(target)
    else:
        ll.target_count = max(ll.target_count, ll.leads.count() + 30)
    ll.pending_search = True
    ll.save()
    if new_prompt:
        importer.log_event(ll, "user", new_prompt)
    importer.log_event(ll, "system", f"Continuing — target raised to {ll.target_count} leads.")
    return JsonResponse({"ok": True, "target": ll.target_count})


@staff_member_required
def api_leadlist_events(request, list_id):
    """The lead list's activity thread (the "AI chat"): your prompts and what
    the finder did each run, newest last."""
    from django.utils import timezone as _tz

    from linkedin.models import LeadList

    ll = LeadList.objects.filter(pk=list_id).first()
    if not ll:
        return JsonResponse({"error": "not found"}, status=404)

    def when(dt):
        d = _tz.localtime(dt)
        return d.strftime("%-d %b %H:%M")

    events = [
        {"role": e.role, "text": e.text, "meta": e.meta, "at": when(e.created_at)}
        for e in ll.events.all()
    ]
    return JsonResponse({"name": ll.name, "source": ll.source_type, "events": events})


@csrf_exempt
@staff_member_required
@require_POST
def api_inbox_send(request, thread_id):
    """Queue a manual reply typed in the Unibox; the worker sends it from the
    thread's owning account on its next cycle."""
    import hashlib

    from django.utils import timezone

    from linkedin.models import Message, MessageThread

    t = MessageThread.objects.filter(pk=thread_id).first()
    if not t:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    body = (payload.get("body") or "").strip()
    if not body:
        return JsonResponse({"error": "empty message"}, status=400)
    mid = "manual-" + hashlib.sha1((body + str(timezone.now())).encode()).hexdigest()[:16]
    Message.objects.create(
        thread=t, direction="out", body=body, sent_via_tool=True, pending_send=True,
        sender_account=t.account, linkedin_message_id=mid, sent_at=timezone.now(),
    )
    t.last_message_at = timezone.now()
    t.contacted_by_tool = True  # a manual reply is us contacting them
    t.save(update_fields=["last_message_at", "contacted_by_tool"])
    return JsonResponse({"ok": True, "queued": True})


@staff_member_required
def api_leadlist_export(request, list_id):
    from linkedin.models import LeadList

    ll = LeadList.objects.filter(pk=list_id).first()
    if not ll:
        return JsonResponse({"error": "not found"}, status=404)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="leads-{ll.pk}.csv"'
    w = _csv.writer(resp)
    w.writerow(["first_name", "last_name", "title", "company", "location", "ai_score", "ai_reason", "linkedin_url", "public_identifier"])
    for lead in ll.leads.all().order_by("-ai_score"):
        w.writerow([
            lead.first_name, lead.last_name, lead.title, lead.company, lead.location,
            lead.ai_score if lead.ai_score is not None else "", lead.ai_reason,
            lead.linkedin_url, lead.public_identifier,
        ])
    return resp


@csrf_exempt
@staff_member_required
@require_POST
def api_create_sequence(request):
    from linkedin.models import Sequence

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "").strip() or "New sequence"
    seq = Sequence.objects.create(name=name, owner=request.user)
    return JsonResponse({"id": seq.pk, "name": seq.name})


_STEP_DEFAULTS = {
    "connect": {"wait_days_before_branch_decision": 14, "personalised_note": ""},
    "message": {"template": "Hi {first_name},"},
    "inmail": {"subject": "", "body": ""},
    "wait": {"days": 2},
    "profile_visit": {},
    "like_post": {},
    "end": {},
}


@csrf_exempt
@staff_member_required
@require_POST
def api_sequence_archive(request, sequence_id):
    from linkedin.models import Sequence

    seq = Sequence.objects.filter(pk=sequence_id).first()
    if not seq:
        return JsonResponse({"error": "not found"}, status=404)
    seq.archive()  # soft-delete (recoverable); hidden from the picker
    return JsonResponse({"ok": True})


@csrf_exempt
@staff_member_required
@require_POST
def api_sequence_rename(request, sequence_id):
    from linkedin.models import Sequence

    seq = Sequence.objects.filter(pk=sequence_id).first()
    if not seq:
        return JsonResponse({"error": "not found"}, status=404)
    name = (json.loads(request.body or "{}").get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    seq.name = name[:200]
    seq.save(update_fields=["name"])
    return JsonResponse({"ok": True})


@csrf_exempt
@staff_member_required
@require_POST
def api_create_step(request, sequence_id):
    from linkedin.models import Sequence, SequenceStep

    seq = Sequence.objects.filter(pk=sequence_id).first()
    if not seq:
        return JsonResponse({"error": "not found"}, status=404)
    payload = json.loads(request.body or "{}")
    step_type = payload.get("step_type")
    if step_type not in SequenceStep.StepType.values:
        return JsonResponse({"error": "bad step_type"}, status=400)
    branch = payload.get("branch", SequenceStep.Branch.ROOT)
    if branch not in SequenceStep.Branch.values:
        return JsonResponse({"error": "bad branch"}, status=400)
    parent = None
    if payload.get("parent_id"):
        parent = SequenceStep.objects.filter(pk=payload["parent_id"], sequence=seq).first()
    # If this (parent, branch) slot already holds a step, INSERT the new step
    # before it: the new step takes the slot and the old child re-parents onto
    # the new step's success branch (linear continuation).
    existing = SequenceStep.objects.filter(sequence=seq, parent=parent, branch=branch).first()
    if step_type == SequenceStep.StepType.END and existing:
        return JsonResponse({"error": "End can only be added where the path currently stops"}, status=400)
    step = SequenceStep.objects.create(
        sequence=seq, parent=parent, branch=branch, step_type=step_type,
        config=_STEP_DEFAULTS.get(step_type, {}), order_in_branch=0,
    )
    if existing:
        existing.parent = step
        existing.branch = SequenceStep.Branch.SUCCESS
        existing.save(update_fields=["parent", "branch"])
    return JsonResponse({"id": step.pk, "inserted_before": existing.pk if existing else None})


@staff_member_required
def api_kpis(request):
    from datetime import timedelta

    from django.utils import timezone

    from linkedin.models import ActionLog, LeadCampaignState, MessageThread

    State = LeadCampaignState.State
    days = int(request.GET.get("days") or 0)
    campaign = request.GET.get("campaign") or None
    since = timezone.now() - timedelta(days=days) if days else None

    def actions(t):
        q = ActionLog.objects.filter(action_type=t)
        if since:
            q = q.filter(created_at__gte=since)
        if campaign:
            q = q.filter(campaign_id=campaign)
        return q.count()

    def states(s):
        q = LeadCampaignState.objects.filter(state=s)
        if campaign:
            q = q.filter(campaign_id=campaign)
        return q.count()

    replies_q = MessageThread.objects.filter(messages__direction="in")
    if since:
        replies_q = replies_q.filter(messages__direction="in", messages__sent_at__gte=since)
    if campaign:
        replies_q = replies_q.filter(lead__campaign_states__campaign_id=campaign)

    return JsonResponse({
        "connection_requests": actions("connect"),
        "messages_sent": actions("message"),
        "inmails_sent": actions("inmail"),
        "replies": replies_q.distinct().count(),
        "active": states(State.ACTIVE),
        "completed": states(State.COMPLETED),
    })


@staff_member_required
def api_senders(request):
    from linkedin.accounts.limits import daily_count
    from linkedin.models import LinkedInProfile

    senders = []
    for a in LinkedInProfile.objects.all():
        caps = a.daily_caps_json or {}
        senders.append({
            "id": a.pk,
            "username": a.linkedin_username,
            "active": a.active,
            "has_inmail": a.has_inmail,
            "usage": {k: {"used": daily_count(a, k), "cap": v} for k, v in caps.items()},
        })
    return JsonResponse({"senders": senders})


@staff_member_required
def api_sequences(request):
    from linkedin.models import Sequence

    seqs = Sequence.objects.filter(archived_at__isnull=True).order_by("name")
    return JsonResponse({"sequences": [{"id": s.pk, "name": s.name} for s in seqs]})


@staff_member_required
def api_sequence(request, sequence_id):
    from linkedin.models import Sequence, SequenceStep

    seq = Sequence.objects.filter(pk=sequence_id).first()
    if not seq:
        return JsonResponse({"error": "not found"}, status=404)

    def node(step):
        return {
            "id": step.pk,
            "step_type": step.step_type,
            "branch": step.branch,
            "config": step.config,
            "success": [node(c) for c in step.children.filter(branch=SequenceStep.Branch.SUCCESS).order_by("order_in_branch")],
            "failure": [node(c) for c in step.children.filter(branch=SequenceStep.Branch.FAILURE).order_by("order_in_branch")],
        }

    root = seq.root_step
    return JsonResponse({"id": seq.pk, "name": seq.name, "root": node(root) if root else None})
