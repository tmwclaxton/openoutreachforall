# linkedin/dashboard/views.py
"""Dashboard JSON API + page (the visual layer, v1).

KPI tiles, a senders table with live cap usage, and a sequence rendered as a
branching flow graph — the HeyReach-style surfaces, served as JSON to a
self-contained page (no SPA build pipeline).
"""
from __future__ import annotations

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
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
    # One child per (parent, branch) — reject duplicates so the tree stays clean.
    if SequenceStep.objects.filter(sequence=seq, parent=parent, branch=branch).exists():
        return JsonResponse({"error": "branch already has a step"}, status=400)
    step = SequenceStep.objects.create(
        sequence=seq, parent=parent, branch=branch, step_type=step_type,
        config=_STEP_DEFAULTS.get(step_type, {}), order_in_branch=0,
    )
    return JsonResponse({"id": step.pk})


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
