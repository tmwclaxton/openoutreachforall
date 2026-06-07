# tests/db/test_lead_campaign_state.py
"""LeadCampaignState transitions + invariants (M2)."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from tests.factories import UserFactory


def _campaign_and_lead():
    from crm.models import Lead
    from linkedin.models import Campaign

    campaign = Campaign.objects.create(name="C")
    lead = Lead.objects.create(
        linkedin_url="https://www.linkedin.com/in/x/", public_identifier="x",
    )
    return campaign, lead


@pytest.mark.django_db
class TestLeadCampaignState:
    def test_unique_per_lead_campaign(self):
        from linkedin.models import LeadCampaignState

        campaign, lead = _campaign_and_lead()
        LeadCampaignState.objects.create(lead=lead, campaign=campaign)
        with pytest.raises(IntegrityError):
            LeadCampaignState.objects.create(lead=lead, campaign=campaign)

    def test_default_state_active(self):
        from linkedin.models import LeadCampaignState

        campaign, lead = _campaign_and_lead()
        state = LeadCampaignState.objects.create(lead=lead, campaign=campaign)
        assert state.state == LeadCampaignState.State.ACTIVE
        assert state.awaiting_decision is False

    def test_terminal_states_retire_without_deletion(self):
        from linkedin.models import LeadCampaignState

        campaign, lead = _campaign_and_lead()
        state = LeadCampaignState.objects.create(lead=lead, campaign=campaign)
        state.state = LeadCampaignState.State.STOPPED_REPLY
        state.save(update_fields=["state"])
        state.refresh_from_db()
        # Retired, not deleted.
        assert LeadCampaignState.objects.filter(pk=state.pk).exists()
        assert state.state == LeadCampaignState.State.STOPPED_REPLY
