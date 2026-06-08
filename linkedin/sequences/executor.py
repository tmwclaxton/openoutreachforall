# linkedin/sequences/executor.py
"""Sequence executor — advances ``LeadCampaignState`` through a Sequence tree.

Polls due, active states; runs the current step's action; routes to the right
branch child (``success``=accepted/replied, ``failure``=not-accepted/no-reply)
or completes. Browser actions are isolated behind small module-level helpers so
unit tests can mock them. Coexists with the autonomous AI-discovery path — only
campaigns with a ``sequence`` are driven here.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from linkedin.models import ActionLog, LeadCampaignState, SequenceStep

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_DECISION_DAYS = 14
Branch = SequenceStep.Branch


# ── Enrollment ────────────────────────────────────────────────────────


def enroll_campaign(campaign) -> int:
    """Create ACTIVE states (due now, at the sequence root) for every lead in the
    campaign's lead_list that isn't already enrolled. Idempotent. Returns count.
    """
    if not campaign.sequence_id or not campaign.lead_list_id:
        return 0
    root = campaign.sequence.root_step
    if root is None:
        return 0

    from crm.models import Lead

    existing = set(
        LeadCampaignState.objects.filter(campaign=campaign).values_list("lead_id", flat=True)
    )
    created = 0
    for lead in Lead.objects.filter(lead_list_id=campaign.lead_list_id):
        if lead.pk in existing:
            continue
        LeadCampaignState.objects.create(
            lead=lead,
            campaign=campaign,
            current_step=root,
            current_branch=Branch.ROOT,
            state=LeadCampaignState.State.ACTIVE,
            next_action_due_at=timezone.now(),
        )
        created += 1
    return created


# ── Executor loop ─────────────────────────────────────────────────────


def due_states(campaign=None):
    qs = LeadCampaignState.objects.filter(
        state=LeadCampaignState.State.ACTIVE,
        next_action_due_at__lte=timezone.now(),
    )
    if campaign is not None:
        qs = qs.filter(campaign=campaign)
    return qs.select_related("current_step", "lead", "campaign")


def run_due_states(session, campaign=None, limit=None) -> int:
    """Execute every due state once. Returns the number advanced."""
    qs = due_states(campaign)
    if limit:
        qs = qs[:limit]
    count = 0
    for state in list(qs):
        try:
            advance_state(session, state)
            count += 1
        except Exception:
            logger.exception("Sequence step failed for %s", state)
            _set_state(state, LeadCampaignState.State.STOPPED_ERROR)
    return count


_STEP_ACTION = {
    SequenceStep.StepType.CONNECT: ActionLog.ActionType.CONNECT,
    SequenceStep.StepType.MESSAGE: ActionLog.ActionType.MESSAGE,
    SequenceStep.StepType.INMAIL: ActionLog.ActionType.INMAIL,
    SequenceStep.StepType.PROFILE_VISIT: ActionLog.ActionType.PROFILE_VISIT,
    SequenceStep.StepType.LIKE_POST: ActionLog.ActionType.LIKE_POST,
}


def advance_state(session, state) -> None:
    step = state.current_step
    if step is None:
        _complete(state)
        return
    # M6: defer when this account is at its daily cap for the step's action.
    action = _STEP_ACTION.get(step.step_type)
    consumes_cap = action and not (
        step.step_type == SequenceStep.StepType.CONNECT and state.awaiting_decision
    )
    if consumes_cap:
        from linkedin.accounts.limits import has_capacity
        if not has_capacity(session.linkedin_profile, action):
            _defer_to_tomorrow(state)
            return
    handler = _HANDLERS.get(step.step_type)
    if handler is None:
        raise ValueError(f"Unknown step_type {step.step_type!r}")
    handler(session, state, step)


# ── Step handlers ─────────────────────────────────────────────────────


def _handle_connect(session, state, step):
    if not state.awaiting_decision:
        send_connection_request(session, state, step)
        _log(session, state, step, ActionLog.ActionType.CONNECT)
        wait_days = int(step.config.get("wait_days_before_branch_decision", DEFAULT_CONNECT_DECISION_DAYS))
        state.awaiting_decision = True
        state.last_action_at = timezone.now()
        state.next_action_due_at = timezone.now() + timedelta(days=wait_days)
        state.save(update_fields=["awaiting_decision", "last_action_at", "next_action_due_at"])
        return
    # Decision phase: accepted → success branch, else → failure branch.
    accepted = is_connection_accepted(session, state)
    state.awaiting_decision = False
    branch = Branch.SUCCESS if accepted else Branch.FAILURE
    _goto(state, step.next_step(branch))


def _handle_message(session, state, step):
    send_message(session, state, step)
    _log(session, state, step, ActionLog.ActionType.MESSAGE)
    # Continue down the no-reply (failure) branch; M3 reply detection halts on reply.
    _goto(state, step.next_step(Branch.FAILURE))


def _handle_inmail(session, state, step):
    result = send_inmail(session, state, step)
    if result.get("success"):
        _log(session, state, step, ActionLog.ActionType.INMAIL)
    else:
        logger.info("InMail not sent for %s (%s) — continuing", state, result.get("error"))
    _goto(state, step.next_step(Branch.SUCCESS))


def _handle_wait(session, state, step):
    days = int(step.config.get("days", 0))
    _goto(state, step.next_step(Branch.SUCCESS), delay=timedelta(days=days))


def _handle_profile_visit(session, state, step):
    visit_profile(session, state)
    _log(session, state, step, ActionLog.ActionType.PROFILE_VISIT)
    _goto(state, step.next_step(Branch.SUCCESS))


def _handle_like_post(session, state, step):
    like_recent_post(session, state)
    _log(session, state, step, ActionLog.ActionType.LIKE_POST)
    _goto(state, step.next_step(Branch.SUCCESS))


_HANDLERS = {
    SequenceStep.StepType.CONNECT: _handle_connect,
    SequenceStep.StepType.MESSAGE: _handle_message,
    SequenceStep.StepType.INMAIL: _handle_inmail,
    SequenceStep.StepType.WAIT: _handle_wait,
    SequenceStep.StepType.PROFILE_VISIT: _handle_profile_visit,
    SequenceStep.StepType.LIKE_POST: _handle_like_post,
}


# ── Cursor movement ───────────────────────────────────────────────────


def _goto(state, next_step, delay=None):
    if next_step is None:
        _complete(state)
        return
    state.current_step = next_step
    state.current_branch = next_step.branch
    state.last_action_at = timezone.now()
    state.next_action_due_at = timezone.now() + (delay or timedelta(0))
    state.save(update_fields=[
        "current_step", "current_branch", "last_action_at", "next_action_due_at",
    ])


def _complete(state):
    state.state = LeadCampaignState.State.COMPLETED
    state.next_action_due_at = None
    state.save(update_fields=["state", "next_action_due_at"])


def _defer_to_tomorrow(state):
    state.next_action_due_at = timezone.now() + timedelta(days=1)
    state.save(update_fields=["next_action_due_at"])


def _set_state(state, new_state):
    state.state = new_state
    state.save(update_fields=["state"])


def _log(session, state, step, action_type):
    from linkedin.accounts.limits import record_action

    ActionLog.objects.create(
        linkedin_profile=session.linkedin_profile,
        campaign=state.campaign,
        action_type=action_type,
        sequence_step=step,
    )
    record_action(session.linkedin_profile, action_type)


# ── Template rendering ────────────────────────────────────────────────


def render_template(template: str, context: dict, fallback: str = "") -> str:
    """Render a template against ``context``. Supports both HeyReach-style
    ``{first_name}`` placeholders and Jinja ``{{ first_name }}``. Empty result
    falls back to ``fallback``.
    """
    if not template:
        return fallback
    try:
        import re

        # {var} (single brace, no spaces) → context value; leaves {{ }} for Jinja.
        text = re.sub(r"\{(\w+)\}", lambda m: str(context.get(m.group(1), "")), template)
        from jinja2 import Template
        rendered = Template(text).render(**context).strip()
    except Exception:
        return fallback
    return rendered or fallback


def _lead_context(state) -> dict:
    lead = state.lead
    return {
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "company": lead.company or "",
        "public_identifier": lead.public_identifier,
    }


# ── Browser-action wrappers (mocked in tests) ─────────────────────────


def send_connection_request(session, state, step):
    from linkedin_cli.actions.connect import send_connection_request as _send
    from linkedin_cli.actions.status import get_connection_status

    lead = state.lead
    pdict = {"public_identifier": lead.public_identifier, "url": lead.linkedin_url, "urn": lead.urn or ""}
    # The connect verb assumes the profile page is already open; this navigates there.
    get_connection_status(session, lead.public_identifier)
    # NOTE: linkedin_cli's active connect flow sends WITHOUT a note; the
    # personalised_note config is not yet wired (needs an app-side with-note flow).
    _send(session, pdict)


def is_connection_accepted(session, state) -> bool:
    from linkedin_cli.actions.status import get_connection_status
    from linkedin_cli.enums import ProfileState

    status = get_connection_status(session, state.lead.public_identifier)
    return str(status) == str(ProfileState.CONNECTED)


def send_message(session, state, step):
    from linkedin_cli.actions.message import send_raw_message

    lead = state.lead
    body = render_template(
        step.config.get("template", ""),
        _lead_context(state),
        step.config.get("fallback", ""),
    )
    urn = lead.urn or lead.get_urn(session)
    pdict = {"public_identifier": lead.public_identifier, "url": lead.linkedin_url, "urn": urn}
    send_raw_message(session, pdict, body)


def send_inmail(session, state, step):
    from linkedin.actions.inmail import send_inmail as _send

    ctx = _lead_context(state)
    subject = render_template(step.config.get("subject", ""), ctx, step.config.get("subject_fallback", ""))
    body = render_template(step.config.get("body", ""), ctx, step.config.get("body_fallback", ""))
    return _send(session, state.lead, subject, body)


def visit_profile(session, state):
    from linkedin_cli.actions.search import visit_profile as _visit

    _visit(session, {"public_identifier": state.lead.public_identifier, "url": state.lead.linkedin_url})


def like_recent_post(session, state):
    from linkedin.actions.like import like_most_recent_post

    return like_most_recent_post(session, state.lead)
