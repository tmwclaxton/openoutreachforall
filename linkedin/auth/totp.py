# linkedin/auth/totp.py
"""Native RFC 6238 TOTP (Google Authenticator) — no external dependency.

Generates the current 6-digit code from a base32 secret so the kit can clear
LinkedIn's 2FA challenge itself instead of waiting for a human to type it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time


def current_totp(secret: str, *, t: float | None = None, digits: int = 6, period: int = 30) -> str:
    """Return the current TOTP code for a base32 ``secret`` (RFC 6238, SHA-1).

    ``t`` overrides the Unix time (for testing). Spaces in the secret are
    ignored and missing base32 padding is added.
    """
    cleaned = secret.replace(" ", "").upper()
    cleaned += "=" * (-len(cleaned) % 8)
    key = base64.b32decode(cleaned)

    counter = int((time.time() if t is None else t) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)
