# linkedin/notify/slack.py
"""Slack notifications for LinkedIn events — a dedicated Incoming Webhook,
deliberately separate from any other project's Slack setup.

Mirrors the CPAK pattern (notify-on-event, gated by an enabled flag) but uses
a single per-channel webhook URL stored in ``SiteConfig`` so it's self-contained
and editable from the dashboard. Failures never raise into the caller.
"""
from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def post_text(text: str, *, webhook_url: str | None = None) -> bool:
    """POST a markdown message to the configured Slack webhook. Returns True on
    success. Swallows all errors (logs a warning) — Slack must never break a
    polling/sending cycle."""
    from linkedin.models import SiteConfig

    url = webhook_url or SiteConfig.load().slack_webhook_url
    if not url:
        return False
    try:
        req = Request(
            url,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted, user-set webhook)
            return 200 <= resp.status < 300
    except Exception as exc:
        logger.warning("Slack notify failed: %r", exc)
        return False


def notify_reply(lead_name: str, message_text: str, lead_url: str, account_name: str) -> bool:
    """Notify that a lead replied — only if reply notifications are enabled and a
    webhook is set."""
    from linkedin.models import SiteConfig

    cfg = SiteConfig.load()
    if not cfg.slack_notify_replies or not cfg.slack_webhook_url:
        return False
    body = (message_text or "").strip()
    quoted = "\n".join(f"> {line}" for line in body.splitlines()) or "> (no text)"
    text = (
        f":speech_balloon: *New LinkedIn reply from {lead_name}*\n"
        f"{quoted}\n"
        f"<{lead_url}|View on LinkedIn> · via {account_name}"
    )
    return post_text(text, webhook_url=cfg.slack_webhook_url)
