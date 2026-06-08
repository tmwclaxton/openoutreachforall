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
    """Edit a sequence step's config (the in-dashboard flow editor)."""
    from linkedin.models import SequenceStep

    step = SequenceStep.objects.filter(pk=step_id).first()
    if not step:
        return JsonResponse({"error": "not found"}, status=404)
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "bad json"}, status=400)
    new_config = payload.get("config")
    if not isinstance(new_config, dict):
        return JsonResponse({"error": "config must be an object"}, status=400)
    step.config = new_config
    step.save(update_fields=["config"])
    return JsonResponse({"ok": True, "config": step.config})


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
    for c in Campaign.objects.filter(sequence__isnull=False).order_by("-id"):
        out.append({
            "id": c.pk,
            "name": c.name,
            "status": c.status,
            "sequence": c.sequence.name if c.sequence else "",
            "lead_list": c.lead_list.name if c.lead_list else "",
            "leads": c.lead_states.count(),
        })
    return JsonResponse({"campaigns": out})


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
    base = MessageThread.objects.filter(messages__isnull=False)
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
        lists.append({"id": ll.pk, "name": ll.name, "source": ll.source_type, "count": ll.leads.count()})
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
    ll.pending_search = True
    ll.save(update_fields=["pending_search"])
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
    ll.pending_search = True
    ll.save(update_fields=["pending_search"])
    return JsonResponse({"ok": True, "queued": True, "list_id": ll.pk})


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
    t.save(update_fields=["last_message_at"])
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
}


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
    from linkedin.models import ActionLog, LeadCampaignState, MessageThread

    State = LeadCampaignState.State

    def actions(t):
        return ActionLog.objects.filter(action_type=t).count()

    def states(s):
        return LeadCampaignState.objects.filter(state=s).count()

    return JsonResponse({
        "connection_requests": actions("connect"),
        "messages_sent": actions("message"),
        "inmails_sent": actions("inmail"),
        # Conversations with at least one inbound message from the lead.
        "replies": MessageThread.objects.filter(messages__direction="in").distinct().count(),
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
