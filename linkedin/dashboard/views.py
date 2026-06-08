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
def api_inbox_accounts(request):
    from linkedin.models import LinkedInProfile

    return JsonResponse({"accounts": [
        {"id": a.pk, "name": a.linkedin_username} for a in LinkedInProfile.objects.all()
    ]})


@staff_member_required
def api_inbox_threads(request):
    from linkedin.models import MessageThread

    account = request.GET.get("account")
    qs = MessageThread.objects.select_related("lead", "account").order_by("-last_message_at", "-created_at")
    if account:
        qs = qs.filter(account_id=account)

    threads = []
    for t in qs[:300]:
        last = t.messages.order_by("-sent_at", "-fetched_at").first()
        threads.append({
            "id": t.pk,
            "lead_name": _lead_name(t.lead),
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


@csrf_exempt
@staff_member_required
@require_POST
def api_leads_search(request):
    """Queue a LinkedIn people search (URL or keyword). The browser worker
    scrapes it on its next cycle (one process owns the LinkedIn session).
    """
    from linkedin.leads import importer
    from linkedin.models import LeadList

    payload = json.loads(request.body or "{}")
    name = (payload.get("name") or "Search import").strip()
    query = (payload.get("query") or "").strip()
    if not query:
        return JsonResponse({"error": "query required"}, status=400)
    url = query if query.startswith("http") else (
        "https://www.linkedin.com/search/results/people/?keywords=" + quote(query)
    )
    ll = importer.create_lead_list(
        name=name, owner=request.user, source_type=LeadList.SourceType.SEARCH_URL, source_url=url,
    )
    ll.pending_search = True
    ll.save(update_fields=["pending_search"])
    return JsonResponse({"ok": True, "queued": True, "list_id": ll.pk})


@staff_member_required
def api_leadlist_export(request, list_id):
    from linkedin.models import LeadList

    ll = LeadList.objects.filter(pk=list_id).first()
    if not ll:
        return JsonResponse({"error": "not found"}, status=404)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="leads-{ll.pk}.csv"'
    w = _csv.writer(resp)
    w.writerow(["linkedin_url", "public_identifier", "first_name", "last_name", "company"])
    for lead in ll.leads.all():
        w.writerow([lead.linkedin_url, lead.public_identifier, lead.first_name, lead.last_name, lead.company])
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
    from linkedin.models import ActionLog, LeadCampaignState

    State = LeadCampaignState.State

    def actions(t):
        return ActionLog.objects.filter(action_type=t).count()

    def states(s):
        return LeadCampaignState.objects.filter(state=s).count()

    return JsonResponse({
        "connection_requests": actions("connect"),
        "messages_sent": actions("message"),
        "inmails_sent": actions("inmail"),
        "replies": states(State.STOPPED_REPLY),
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
