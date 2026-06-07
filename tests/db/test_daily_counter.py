# tests/db/test_daily_counter.py
"""AccountDailyCounter + capacity (M6)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone


def _account(caps):
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    u = User.objects.create(username=f"u{User.objects.count()}")
    return LinkedInProfile.objects.create(
        user=u, linkedin_username="a@b.c", linkedin_password="x", daily_caps_json=caps,
    )


@pytest.mark.django_db
class TestDailyCounter:
    def test_increments_one_row_per_day(self):
        from linkedin.accounts.limits import daily_count, record_action
        from linkedin.models import AccountDailyCounter

        acct = _account({"connect": 25})
        assert record_action(acct, "connect") == 1
        assert record_action(acct, "connect") == 2
        assert AccountDailyCounter.objects.filter(account=acct, action_type="connect").count() == 1
        assert daily_count(acct, "connect") == 2

    def test_separate_row_per_day(self):
        from linkedin.accounts.limits import record_action
        from linkedin.models import AccountDailyCounter

        acct = _account({"connect": 25})
        today = timezone.now().date()
        record_action(acct, "connect", date=today)
        record_action(acct, "connect", date=today - timedelta(days=1))
        assert AccountDailyCounter.objects.filter(account=acct, action_type="connect").count() == 2

    def test_has_capacity_respects_cap(self):
        from linkedin.accounts.limits import has_capacity, record_action

        acct = _account({"connect": 2})
        assert has_capacity(acct, "connect")
        record_action(acct, "connect")
        record_action(acct, "connect")
        assert not has_capacity(acct, "connect")
