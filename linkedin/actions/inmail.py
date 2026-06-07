# linkedin/actions/inmail.py
"""InMail send action (M4).

``linkedin_cli`` has no InMail primitive, so this is an app-side Playwright
action. Gated by the account's ``has_inmail`` capability (Sales Navigator /
Recruiter); when unavailable it **skips cleanly** so a sequence never crashes.
The browser composer lives in ``_compose_inmail`` (mocked in tests).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def send_inmail(session, lead, subject: str, body: str) -> dict:
    """Send an InMail to ``lead``.

    Returns ``{success, skipped, error, linkedin_message_id}``. Never raises:
    a missing-capability account yields ``skipped=True``; a UI failure yields
    ``success=False`` with the error captured.
    """
    if not session.linkedin_profile.has_inmail:
        logger.warning(
            "InMail unavailable for %s — skipping (no Sales Navigator/Recruiter)",
            session.linkedin_profile,
        )
        return {"success": False, "skipped": True, "error": "no_inmail", "linkedin_message_id": None}

    try:
        message_id = _compose_inmail(session, lead, subject, body)
    except Exception as exc:  # UI flow is brittle; never crash the sequence.
        logger.exception("InMail send failed for %s", lead)
        return {"success": False, "skipped": False, "error": str(exc), "linkedin_message_id": None}

    return {"success": True, "skipped": False, "error": None, "linkedin_message_id": message_id}


def _compose_inmail(session, lead, subject: str, body: str):
    """Drive the LinkedIn InMail composer over Playwright (best-effort UI flow).

    Mocked in tests. Returns a message id when resolvable, else None.
    """
    from linkedin_cli.browser.nav import goto_page

    session.ensure_browser()
    page = session.page
    goto_page(
        session,
        action=lambda: page.goto(lead.linkedin_url, wait_until="domcontentloaded"),
        expected_url_pattern=f"/in/{lead.public_identifier}",
        error_message="Failed to open profile for InMail",
    )
    page.get_by_role("button", name="Message").first.click()
    if subject:
        page.get_by_label("Subject").fill(subject)
    page.get_by_role("textbox").last.fill(body)
    page.get_by_role("button", name="Send").click()
    return None
