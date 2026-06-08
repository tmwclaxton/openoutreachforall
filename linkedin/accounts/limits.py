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


def cap_for(account, action_type, date=None) -> int:
    from linkedin.models import default_daily_caps

    # Connection requests can use a randomised daily cap within [min, max], picked
    # deterministically per (account, day) so it's stable across the day / restarts.
    if action_type == "connect" and getattr(account, "connect_random_enabled", False):
        import random as _random

        lo = int(account.connect_random_min or 0)
        hi = int(account.connect_random_max or 0)
        if hi < lo:
            lo, hi = hi, lo
        if hi > 0:
            d = date or timezone.now().date()
            seed = account.pk * 1_000_000 + d.toordinal()  # stable, not process-salted
            return _random.Random(seed).randint(lo, hi)

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


# ── Per-account send schedule + paced "drip" ──────────────────────────


def _account_tz(account):
    from zoneinfo import ZoneInfo

    try:
        return ZoneInfo(account.send_timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _is_bank_holiday(account, local_date) -> bool:
    if not account.skip_bank_holidays:
        return False
    try:
        import holidays  # optional dep; degrades to "no holidays" if absent
    except ImportError:
        logger.warning("skip_bank_holidays set but 'holidays' package not installed — ignoring")
        return False
    try:
        cal = holidays.country_holidays(account.holiday_country or "GB", years=local_date.year)
        return local_date in cal
    except Exception:
        return False


def is_send_time(account, dt=None) -> bool:
    """True if ``dt`` (default now) is inside the account's send window: right
    weekday, not a skipped bank holiday, and within [start, end) local hours."""
    dt = dt or timezone.now()
    local = dt.astimezone(_account_tz(account))
    weekdays = account.send_weekdays or [0, 1, 2, 3, 4]
    if local.weekday() not in weekdays:
        return False
    if _is_bank_holiday(account, local.date()):
        return False
    return account.send_start_hour <= local.hour < account.send_end_hour


def next_send_time(account, dt=None):
    """Earliest send-eligible moment at or after ``dt`` for this account."""
    from datetime import timedelta

    dt = dt or timezone.now()
    tz = _account_tz(account)
    weekdays = account.send_weekdays or [0, 1, 2, 3, 4]
    local = dt.astimezone(tz)
    for _ in range(367):  # at most a year ahead
        ok_day = local.weekday() in weekdays and not _is_bank_holiday(account, local.date())
        if ok_day:
            win_start = local.replace(hour=account.send_start_hour, minute=0, second=0, microsecond=0)
            win_end = local.replace(hour=account.send_end_hour, minute=0, second=0, microsecond=0)
            if local < win_start:
                return win_start  # window opens later today (tz-aware)
            if local < win_end:
                return local  # already inside the window (== dt on the first pass)
        # advance to the start of the next calendar day, local time
        local = (local + timedelta(days=1)).replace(
            hour=account.send_start_hour, minute=0, second=0, microsecond=0,
        )
    return dt


def _window_seconds(account) -> float:
    hours = max(1, (account.send_end_hour - account.send_start_hour))
    return hours * 3600.0


def _last_action_at(account, action_type):
    from linkedin.models import ActionLog

    return (
        ActionLog.objects.filter(linkedin_profile=account, action_type=action_type)
        .order_by("-created_at").values_list("created_at", flat=True).first()
    )


def next_action_at(account, action_type):
    """When this account may next perform ``action_type`` — paces the day's cap
    evenly across the send window (with mild jitter) so e.g. 25 connects drip out
    over the working day instead of bursting, and never outside the window. A
    return value <= now means 'go now'."""
    import random
    from datetime import timedelta

    from linkedin.conf import ENABLE_ACTION_PACING

    now = timezone.now()
    if not ENABLE_ACTION_PACING:
        return now
    cap = cap_for(account, action_type)
    if cap <= 0:
        return next_send_time(account, now)
    spacing = _window_seconds(account) / cap
    last = _last_action_at(account, action_type)
    base = now if last is None else last + timedelta(seconds=spacing * random.uniform(0.75, 1.25))
    return next_send_time(account, base if base > now else now)


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
