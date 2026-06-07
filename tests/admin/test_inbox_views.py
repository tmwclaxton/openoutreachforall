# tests/admin/test_inbox_views.py
"""Unified inbox admin (M5)."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone


@pytest.fixture
def admin_client(db, client):
    from django.contrib.auth.models import User

    user = User.objects.create_superuser("admin", "admin@example.com", "pw")
    client.force_login(user)
    return client


def _account():
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    u = User.objects.create(username=f"acct{User.objects.count()}")
    return LinkedInProfile.objects.create(user=u, linkedin_username="a@b.c", linkedin_password="x")


def _thread(pid, account, tool_msg=False, read=False):
    from crm.models import Lead
    from linkedin.models import Message, MessageThread

    lead = Lead.objects.create(linkedin_url=f"https://www.linkedin.com/in/{pid}/", public_identifier=pid)
    t = MessageThread.objects.create(
        lead=lead, account=account, last_message_at=timezone.now(),
        read_at=timezone.now() if read else None,
    )
    Message.objects.create(
        thread=t, direction="out" if tool_msg else "in",
        linkedin_message_id=f"{pid}-m", sent_via_tool=tool_msg,
    )
    return t


CHANGELIST = "admin:linkedin_messagethread_changelist"


@pytest.mark.django_db
class TestInbox:
    def test_loads_and_privacy_default(self, admin_client):
        acct = _account()
        _thread("toollead", acct, tool_msg=True)
        _thread("organiclead", acct, tool_msg=False)

        # Default: only tool-initiated threads.
        resp = admin_client.get(reverse(CHANGELIST))
        assert resp.status_code == 200
        assert b"toollead" in resp.content
        assert b"organiclead" not in resp.content

        # scope=all reveals everything.
        all_resp = admin_client.get(reverse(CHANGELIST) + "?scope=all")
        assert b"toollead" in all_resp.content
        assert b"organiclead" in all_resp.content

    def test_unread_filter(self, admin_client):
        acct = _account()
        _thread("alpha", acct, tool_msg=True, read=False)
        _thread("bravo", acct, tool_msg=True, read=True)

        resp = admin_client.get(reverse(CHANGELIST) + "?read=unread")
        assert b"alpha" in resp.content
        assert b"bravo" not in resp.content

    def test_mark_read_endpoint(self, admin_client):
        from linkedin.models import MessageThread

        t = _thread("x", _account(), tool_msg=True)
        assert t.read_at is None
        admin_client.get(reverse("admin:linkedin_messagethread_mark_read", args=[t.pk]))
        t.refresh_from_db()
        assert t.read_at is not None

    def test_pause_campaign_action(self, admin_client):
        from linkedin.models import Campaign, LeadCampaignState

        acct = _account()
        t = _thread("p", acct, tool_msg=True)
        campaign = Campaign.objects.create(name="C")
        state = LeadCampaignState.objects.create(
            lead=t.lead, campaign=campaign, state=LeadCampaignState.State.ACTIVE,
        )
        admin_client.post(
            reverse(CHANGELIST),
            {"action": "pause_campaign", "_selected_action": [t.pk], "scope": "all"},
        )
        state.refresh_from_db()
        assert state.state == LeadCampaignState.State.PAUSED_MANUAL
