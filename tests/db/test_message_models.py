# tests/db/test_message_models.py
"""MessageThread + Message invariants (M3)."""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction


def _thread(fake_session):
    from crm.models import Lead
    from linkedin.models import MessageThread

    lead = Lead.objects.create(linkedin_url="https://www.linkedin.com/in/x/", public_identifier="x")
    return MessageThread.objects.create(lead=lead, account=fake_session.linkedin_profile)


@pytest.mark.django_db
class TestMessageModels:
    def test_message_unique_per_thread(self, fake_session):
        from linkedin.models import Message

        t = _thread(fake_session)
        Message.objects.create(thread=t, direction=Message.Direction.IN, linkedin_message_id="m1")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Message.objects.create(thread=t, direction=Message.Direction.IN, linkedin_message_id="m1")

    def test_thread_unique_per_lead_account(self, fake_session):
        from crm.models import Lead
        from linkedin.models import MessageThread

        lead = Lead.objects.create(linkedin_url="https://www.linkedin.com/in/y/", public_identifier="y")
        MessageThread.objects.create(lead=lead, account=fake_session.linkedin_profile)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MessageThread.objects.create(lead=lead, account=fake_session.linkedin_profile)

    def test_direction_values(self, fake_session):
        from linkedin.models import Message

        t = _thread(fake_session)
        m = Message.objects.create(thread=t, direction=Message.Direction.OUT, linkedin_message_id="o1")
        assert m.direction == "out"
        assert t.has_inbound_reply is False
        assert t.read_at is None  # unread by default (M5)
