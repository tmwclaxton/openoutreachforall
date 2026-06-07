# tests/tasks/test_account_rotation.py
"""Round-robin account selection + cap defer (M6)."""
from __future__ import annotations

import pytest


def _account(caps):
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    u = User.objects.create(username=f"u{User.objects.count()}")
    return LinkedInProfile.objects.create(
        user=u, linkedin_username="a@b.c", linkedin_password="x", daily_caps_json=caps,
    )


def _campaign(accounts):
    from linkedin.models import Campaign

    c = Campaign.objects.create(name=f"C{Campaign.objects.count()}")
    for a in accounts:
        c.users.add(a.user)
    return c


def _run(campaign, action, n):
    """Simulate scheduling ``n`` actions: select + record, or defer (None)."""
    from linkedin.accounts.limits import record_action, select_account

    picks = []
    for _ in range(n):
        acct = select_account(campaign, action)
        if acct is None:
            picks.append(None)
            continue
        record_action(acct, action)
        picks.append(acct.pk)
    return picks


@pytest.mark.django_db
class TestAccountRotation:
    def test_single_account_caps_then_defers(self):
        from linkedin.accounts.limits import daily_count

        acct = _account({"connect": 5})
        picks = _run(_campaign([acct]), "connect", 10)
        assert picks[:5] == [acct.pk] * 5
        assert picks[5:] == [None] * 5
        assert daily_count(acct, "connect") == 5

    def test_round_robin_distributes_across_accounts(self):
        from linkedin.accounts.limits import daily_count

        a = _account({"connect": 5})
        b = _account({"connect": 5})
        picks = _run(_campaign([a, b]), "connect", 10)
        assert None not in picks
        assert daily_count(a, "connect") == 5
        assert daily_count(b, "connect") == 5
        # Genuinely alternated, not all-A-then-all-B.
        assert picks[0] != picks[1]
