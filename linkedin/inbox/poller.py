# linkedin/inbox/poller.py
"""Reply detection (M3).

Polls each active sequence lead's LinkedIn conversation; persists messages as
``Message`` rows (idempotent by ``linkedin_message_id``); and when an inbound
reply has arrived since the lead's last action, sets ``LeadCampaignState`` to
``stopped_reply`` so the sequence never messages a lead who answered.

``fetch_thread_messages`` is the single mockable boundary over ``linkedin_cli``.
NOTE: ``get_conversation`` returns only ``{sender, text, timestamp}`` — it drops
the Voyager entityUrn — so direction is inferred by sender name and the message
id is synthesised from a content hash. Refining this needs a ``linkedin_cli``
change (tracked for the M4-era cli fork).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone as _tz

from django.utils import timezone

logger = logging.getLogger(__name__)


def _parse_ts(ts: str):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=_tz.utc)
    except (ValueError, TypeError):
        return None


def _synth_id(sender: str, text: str, ts: str) -> str:
    return hashlib.sha1(f"{sender}|{ts}|{text}".encode("utf-8")).hexdigest()


def _self_name(session) -> str:
    p = session.self_profile or {}
    return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()


def fetch_thread_messages(session, lead) -> list[dict]:
    """Return ``[{linkedin_message_id, direction, body, sent_at}]`` for the lead's
    conversation. Mocked in tests; thin wrapper over ``linkedin_cli`` in prod.
    """
    from linkedin_cli.actions.conversations import get_conversation

    target_urn = getattr(lead, "urn", None)
    mailbox_urn = (session.self_profile or {}).get("urn")
    if not target_urn or not mailbox_urn:
        return []

    convo = get_conversation(session, target_urn, mailbox_urn) or []
    me = _self_name(session)
    out = []
    for m in convo:
        sender = m.get("sender", "")
        ts = m.get("timestamp", "")
        out.append({
            "linkedin_message_id": _synth_id(sender, m.get("text", ""), ts),
            "direction": "out" if sender == me else "in",
            "body": m.get("text", ""),
            "sent_at": _parse_ts(ts),
        })
    return out


def poll_replies(session, campaign=None) -> int:
    """Poll active sequence leads; persist messages; stop any that replied.
    Returns the number of states transitioned to ``stopped_reply``.
    """
    from linkedin.models import LeadCampaignState, Message, MessageThread

    qs = LeadCampaignState.objects.filter(state=LeadCampaignState.State.ACTIVE)
    if campaign is not None:
        qs = qs.filter(campaign=campaign)

    stopped = 0
    for state in qs.select_related("lead", "campaign"):
        messages = fetch_thread_messages(session, state.lead)
        thread, _ = MessageThread.objects.get_or_create(
            lead=state.lead, account=session.linkedin_profile,
        )

        inbound_reply = False
        latest_ts = thread.last_message_at
        for m in messages:
            Message.objects.get_or_create(
                thread=thread,
                linkedin_message_id=m["linkedin_message_id"],
                defaults={
                    "direction": m["direction"],
                    "body": m["body"],
                    "sent_at": m["sent_at"],
                    "sent_via_tool": False,
                    "sender_account": session.linkedin_profile if m["direction"] == "out" else None,
                },
            )
            if m["sent_at"] and (latest_ts is None or m["sent_at"] > latest_ts):
                latest_ts = m["sent_at"]
            if m["direction"] == "in" and (
                state.last_action_at is None or (m["sent_at"] and m["sent_at"] > state.last_action_at)
            ):
                inbound_reply = True

        thread.last_polled_at = timezone.now()
        thread.last_message_at = latest_ts
        if inbound_reply:
            thread.has_inbound_reply = True
        thread.save()

        if inbound_reply:
            state.state = LeadCampaignState.State.STOPPED_REPLY
            state.save(update_fields=["state"])
            stopped += 1
            logger.info("Lead %s replied — sequence stopped", state.lead_id)

    return stopped
