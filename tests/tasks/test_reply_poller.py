# tests/tasks/test_reply_poller.py
"""Reply detection (M3) — conversation fetch mocked."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone


def _active_state(fake_session, last_action_minutes_ago=60):
    from crm.models import Lead
    from linkedin.models import Campaign, LeadCampaignState

    lead = Lead.objects.create(
        linkedin_url="https://www.linkedin.com/in/x/", public_identifier="x", urn="urn:li:fsd_profile:X",
    )
    campaign = Campaign.objects.first() or Campaign.objects.create(name="C")
    return LeadCampaignState.objects.create(
        lead=lead, campaign=campaign,
        state=LeadCampaignState.State.ACTIVE,
        last_action_at=timezone.now() - timedelta(minutes=last_action_minutes_ago),
    )


@pytest.mark.django_db
class TestReplyPoller:
    def test_inbound_reply_stops_sequence(self, fake_session):
        from linkedin.inbox import poller
        from linkedin.models import LeadCampaignState, Message

        state = _active_state(fake_session)
        msgs = [{"linkedin_message_id": "m1", "direction": "in", "body": "thanks!", "sent_at": timezone.now()}]
        with patch.object(poller, "fetch_thread_messages", return_value=msgs):
            assert poller.poll_replies(fake_session) == 1

        state.refresh_from_db()
        assert state.state == LeadCampaignState.State.STOPPED_REPLY
        assert Message.objects.filter(direction="in").count() == 1

    def test_outbound_only_does_not_stop(self, fake_session):
        from linkedin.inbox import poller
        from linkedin.models import LeadCampaignState

        state = _active_state(fake_session)
        msgs = [{"linkedin_message_id": "o1", "direction": "out", "body": "hi", "sent_at": timezone.now()}]
        with patch.object(poller, "fetch_thread_messages", return_value=msgs):
            assert poller.poll_replies(fake_session) == 0

        state.refresh_from_db()
        assert state.state == LeadCampaignState.State.ACTIVE

    def test_reply_older_than_last_action_ignored(self, fake_session):
        from linkedin.inbox import poller
        from linkedin.models import LeadCampaignState

        state = _active_state(fake_session, last_action_minutes_ago=0)
        old = timezone.now() - timedelta(hours=2)
        msgs = [{"linkedin_message_id": "old", "direction": "in", "body": "earlier", "sent_at": old}]
        with patch.object(poller, "fetch_thread_messages", return_value=msgs):
            assert poller.poll_replies(fake_session) == 0
        state.refresh_from_db()
        assert state.state == LeadCampaignState.State.ACTIVE

    def test_idempotent_no_duplicate_messages(self, fake_session):
        from linkedin.inbox import poller
        from linkedin.models import Message

        _active_state(fake_session)
        msgs = [{"linkedin_message_id": "m1", "direction": "in", "body": "hi", "sent_at": timezone.now()}]
        with patch.object(poller, "fetch_thread_messages", return_value=msgs):
            poller.poll_replies(fake_session)
            poller.poll_replies(fake_session)
        assert Message.objects.filter(linkedin_message_id="m1").count() == 1
