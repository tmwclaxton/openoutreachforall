"""Per-account send window + paced drip + Blank resume."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User

import linkedin.conf as conf
from linkedin.accounts import limits
from linkedin.models import LinkedInProfile


def _account(**kw):
    u = User.objects.create(username=kw.pop("u", "sched_user"))
    defaults = dict(
        user=u, linkedin_username="x@y.com", linkedin_password="p",
        send_start_hour=9, send_end_hour=17, send_timezone="Europe/London",
        send_weekdays=[0, 1, 2, 3, 4],
    )
    defaults.update(kw)
    return LinkedInProfile.objects.create(**defaults)


@pytest.mark.django_db
def test_is_send_time_inside_and_outside_window():
    a = _account()
    tz = ZoneInfo("Europe/London")
    assert limits.is_send_time(a, datetime(2026, 6, 8, 10, 0, tzinfo=tz))   # Mon 10:00
    assert not limits.is_send_time(a, datetime(2026, 6, 8, 8, 0, tzinfo=tz))   # before 09
    assert not limits.is_send_time(a, datetime(2026, 6, 8, 18, 0, tzinfo=tz))  # after 17
    assert not limits.is_send_time(a, datetime(2026, 6, 6, 10, 0, tzinfo=tz))  # Sat


@pytest.mark.django_db
def test_next_send_time_jumps_to_window_open():
    a = _account()
    tz = ZoneInfo("Europe/London")
    # Saturday afternoon → next slot is Monday 09:00 local.
    nxt = limits.next_send_time(a, datetime(2026, 6, 6, 14, 0, tzinfo=tz)).astimezone(tz)
    assert (nxt.weekday(), nxt.hour) == (0, 9)


@pytest.mark.django_db
def test_pacing_defers_after_a_recent_action(monkeypatch):
    monkeypatch.setattr(conf, "ENABLE_ACTION_PACING", True)
    from django.utils import timezone

    from linkedin.models import ActionLog, Campaign
    a = _account(daily_caps_json={"connect": 25})
    camp = Campaign.objects.create(name="c-sched")
    # Inside the window, with a connect just logged → next must be in the future,
    # within roughly one even slot (10h/25 ≈ 24 min, ±25% jitter).
    ActionLog.objects.create(linkedin_profile=a, campaign=camp, action_type="connect")
    monkeypatch.setattr(limits, "is_send_time", lambda acc, dt=None: True)
    monkeypatch.setattr(limits, "next_send_time", lambda acc, dt=None: dt)
    slot = limits.next_action_at(a, "connect")
    delta = (slot - timezone.now()).total_seconds()
    assert 60 < delta < 40 * 60  # spaced out, not immediate


@pytest.mark.django_db
def test_blank_step_resumes_to_next(fake_session):
    from django.utils import timezone

    from linkedin.models import LeadCampaignState, Sequence, SequenceStep
    from crm.models import Lead
    from linkedin.sequences import executor

    seq = Sequence.objects.create(name="s-blank", owner=fake_session.django_user)
    blank = SequenceStep.objects.create(sequence=seq, step_type="blank", branch="root", config={})
    nxt = SequenceStep.objects.create(sequence=seq, parent=blank, branch="success", step_type="wait", config={"days": 3})
    lead = Lead.objects.create(public_identifier="bl", linkedin_url="https://x/in/bl/")
    camp = fake_session.campaign
    st = LeadCampaignState.objects.create(
        lead=lead, campaign=camp, current_step=blank,
        state=LeadCampaignState.State.ACTIVE, next_action_due_at=timezone.now(),
    )
    executor.advance_state(fake_session, st)
    st.refresh_from_db()
    # Blank does nothing but advances the cursor to the next step (resumes).
    assert st.current_step_id == nxt.pk
