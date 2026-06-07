# tests/auth/test_totp.py
"""Native TOTP 2FA (RFC 6238) + auto-fill login."""
from __future__ import annotations

# RFC 6238 SHA-1 test vector: secret = base32("12345678901234567890").
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TestCurrentTotp:
    def test_rfc6238_vector(self):
        from linkedin.auth.totp import current_totp

        # At t=59s the RFC's 8-digit TOTP is 94287082 → 6-digit tail 287082.
        assert current_totp(RFC_SECRET, t=59) == "287082"

    def test_spaces_and_lowercase_and_padding(self):
        from linkedin.auth.totp import current_totp

        spaced = "gezd gnbv gy3t qojq gezd gnbv gy3t qojq"
        assert current_totp(spaced, t=59) == "287082"

    def test_code_is_six_digits(self):
        from linkedin.auth.totp import current_totp

        code = current_totp(RFC_SECRET, t=1234567890)
        assert code.isdigit() and len(code) == 6


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    @property
    def last(self):
        return self

    @property
    def first(self):
        return self

    def fill(self, value):
        self.page.filled.append(("locator", value))

    def click(self):
        self.page.clicked += 1


class _FakePage:
    def __init__(self, url):
        self.url = url
        self.filled = []
        self.clicked = 0

    def goto(self, url, **kw):
        pass

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def get_by_role(self, role, name=None):
        return _FakeLocator(self)

    def get_by_label(self, label):
        return _FakeLocator(self)


class _FakeSession:
    def __init__(self, page):
        self.page = page

    def ensure_browser(self):
        pass


class TestLoginWithTotp:
    def test_fills_credentials_and_2fa_code_on_challenge(self):
        from linkedin.auth.login import login_with_totp

        page = _FakePage(url="https://www.linkedin.com/checkpoint/challenge/AbC")
        login_with_totp(_FakeSession(page), "user@example.com", "pw", RFC_SECRET)

        assert ("#username", "user@example.com") in page.filled
        assert ("#password", "pw") in page.filled
        # A 6-digit code was filled on the challenge page.
        assert any(v.isdigit() and len(v) == 6 for _, v in page.filled)

    def test_no_code_when_not_on_challenge(self):
        from linkedin.auth.login import login_with_totp

        page = _FakePage(url="https://www.linkedin.com/feed/")
        login_with_totp(_FakeSession(page), "user@example.com", "pw", RFC_SECRET)
        assert not any(v.isdigit() and len(v) == 6 for _, v in page.filled)
