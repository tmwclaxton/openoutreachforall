# linkedin/accounts/limits.py
"""Per-account daily caps + least-recently-used round-robin selection (M6).

Every outgoing action is tallied in ``AccountDailyCounter`` (append/increment,
never deleted). Before scheduling an action the caller checks ``has_capacity``;
``select_account`` picks the least-recently-used account in a campaign's pool
that still has headroom, so volume spreads across accounts and no single account
trips LinkedIn's limits.
"""
from __future__ import annotations

import logging

from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


def cap_for(account, action_type) -> int:
    from linkedin.models import default_daily_caps

    caps = account.daily_caps_json or default_daily_caps()
    return int(caps.get(action_type, 0))


def daily_count(account, action_type, date=None) -> int:
    from linkedin.models import AccountDailyCounter

    date = date or timezone.now().date()
    row = AccountDailyCounter.objects.filter(account=account, date=date, action_type=action_type).first()
    return row.count if row else 0


def has_capacity(account, action_type, date=None) -> bool:
    return daily_count(account, action_type, date) < cap_for(account, action_type)


def inmail_sent_this_month(account) -> int:
    from linkedin.models import AccountDailyCounter

    now = timezone.now()
    rows = AccountDailyCounter.objects.filter(
        account=account, action_type="inmail", date__year=now.year, date__month=now.month,
    )
    return sum(r.count for r in rows)


def has_inmail_monthly_capacity(account) -> bool:
    return inmail_sent_this_month(account) < (account.inmail_monthly_cap or 0)


def record_action(account, action_type, date=None) -> int:
    """Increment the day's counter for (account, action_type); stamp last-used.
    Returns the new count. Idempotent row creation by (account, date, type).
    """
    from linkedin.models import AccountDailyCounter

    date = date or timezone.now().date()
    counter, _ = AccountDailyCounter.objects.get_or_create(
        account=account, date=date, action_type=action_type,
    )
    AccountDailyCounter.objects.filter(pk=counter.pk).update(count=F("count") + 1)
    account.last_used_at = timezone.now()
    account.save(update_fields=["last_used_at"])
    counter.refresh_from_db()
    return counter.count


def account_pool(campaign):
    """Active LinkedIn accounts attached to the campaign (via its users)."""
    from linkedin.models import LinkedInProfile

    return list(LinkedInProfile.objects.filter(user__campaigns=campaign, active=True).distinct())


def select_account(campaign, action_type):
    """The least-recently-used account in the pool with remaining capacity, or None
    if all accounts are at their cap for this action today.
    """
    candidates = [a for a in account_pool(campaign) if has_capacity(a, action_type)]
    if not candidates:
        return None
    # Never-used first, then oldest last_used_at — round-robin.
    candidates.sort(key=lambda a: (a.last_used_at is not None, a.last_used_at or timezone.now()))
    return candidates[0]
