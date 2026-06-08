# linkedin/actions/like.py
"""Like a profile's most recent post.

No ``linkedin_cli`` primitive exists, so this is an app-side Playwright flow:
open the lead's recent activity, find the latest post's Like button, click it.
Idempotent — if it's already liked, it reports success without re-clicking.
Never raises: failures are captured in the result.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def like_most_recent_post(session, lead) -> dict:
    try:
        return _like(session, lead)
    except Exception as exc:  # brittle UI flow — never crash the sequence
        logger.exception("Like most recent post failed for %s", lead)
        return {"success": False, "error": str(exc)}


def _like(session, lead) -> dict:
    session.ensure_browser()
    page = session.page
    url = f"https://www.linkedin.com/in/{lead.public_identifier}/recent-activity/all/"
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(2500)
    except Exception:
        pass

    like = page.locator('button[aria-label*="React Like"], button[aria-label="Like"]').first
    if like.count() == 0:
        like = page.get_by_role("button", name="Like").first
    if like.count() == 0:
        return {"success": False, "error": "no Like button found (no recent posts?)"}

    if (like.get_attribute("aria-pressed") or "").lower() == "true":
        logger.info("Most recent post already liked for %s", lead.public_identifier)
        return {"success": True, "already_liked": True}

    like.click()
    logger.info("Liked most recent post for %s", lead.public_identifier)
    return {"success": True, "already_liked": False}
