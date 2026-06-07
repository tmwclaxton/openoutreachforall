# linkedin/auth/login.py
"""App-side LinkedIn login that clears 2FA via a stored TOTP secret.

``linkedin_cli.authenticate`` waits for a human at the 2FA challenge, so when an
account has a ``totp_secret`` we drive login ourselves and auto-fill the code
from :func:`linkedin.auth.totp.current_totp`. Browser steps are best-effort UI
automation (mocked in tests).
"""
from __future__ import annotations

import logging

from linkedin.auth.totp import current_totp

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.linkedin.com/login"


def login_with_totp(session, username: str, password: str, totp_secret: str) -> None:
    session.ensure_browser()
    page = session.page
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill("#username", username)
    page.fill("#password", password)
    page.get_by_role("button", name="Sign in").click()
    _maybe_submit_2fa(session, totp_secret)


def _maybe_submit_2fa(session, totp_secret: str) -> bool:
    """If on a 2FA challenge page, fill + submit the current TOTP code.
    Returns True if a code was submitted.
    """
    page = session.page
    url = (page.url or "").lower()
    if "checkpoint/challenge" not in url and "verification" not in url and "two-step" not in url:
        return False
    code = current_totp(totp_secret)
    page.get_by_role("textbox").last.fill(code)
    page.get_by_role("button", name="Submit").click()
    logger.info("Submitted TOTP 2FA code natively")
    return True
