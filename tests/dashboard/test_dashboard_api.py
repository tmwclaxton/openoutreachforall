# tests/dashboard/test_dashboard_api.py
"""Dashboard JSON API + page (visual layer v1)."""
from __future__ import annotations

import pytest


@pytest.fixture
def admin_client(db, client):
    from django.contrib.auth.models import User

    user = User.objects.create_superuser("admin", "admin@example.com", "pw")
    client.force_login(user)
    return client


def _profile():
    from django.contrib.auth.models import User
    from linkedin.models import LinkedInProfile

    u = User.objects.create(username=f"acct{User.objects.count()}")
    return LinkedInProfile.objects.create(
        user=u, linkedin_username="a@b.c", linkedin_password="p", has_inmail=True,
    )


@pytest.mark.django_db
class TestDashboardApi:
    def test_kpis(self, admin_client):
        from crm.models import Lead
        from linkedin.models import ActionLog, Campaign, LeadCampaignState

        prof = _profile()
        camp = Campaign.objects.create(name="C")
        ActionLog.objects.create(linkedin_profile=prof, campaign=camp, action_type="connect")
        ActionLog.objects.create(linkedin_profile=prof, campaign=camp, action_type="message")
        lead = Lead.objects.create(linkedin_url="https://www.linkedin.com/in/x/", public_identifier="x")
        LeadCampaignState.objects.create(lead=lead, campaign=camp, state=LeadCampaignState.State.STOPPED_REPLY)

        data = admin_client.get("/dashboard/api/kpis/").json()
        assert data["connection_requests"] == 1
        assert data["messages_sent"] == 1
        assert data["replies"] == 1

    def test_senders(self, admin_client):
        prof = _profile()
        data = admin_client.get("/dashboard/api/senders/").json()
        ids = [s["id"] for s in data["senders"]]
        assert prof.pk in ids
        sender = next(s for s in data["senders"] if s["id"] == prof.pk)
        assert sender["has_inmail"] is True
        assert "connect" in sender["usage"]

    def test_sequence_graph(self, admin_client):
        from linkedin.models import Sequence
        from linkedin.models import SequenceStep as S
        from tests.factories import UserFactory

        seq = Sequence.objects.create(name="Seq", owner=UserFactory())
        connect = S.objects.create(sequence=seq, branch=S.Branch.ROOT, step_type=S.StepType.CONNECT)
        S.objects.create(sequence=seq, parent=connect, branch=S.Branch.SUCCESS, step_type=S.StepType.WAIT)
        S.objects.create(sequence=seq, parent=connect, branch=S.Branch.FAILURE, step_type=S.StepType.INMAIL)

        data = admin_client.get(f"/dashboard/api/sequence/{seq.pk}/").json()
        assert data["root"]["step_type"] == "connect"
        assert data["root"]["success"][0]["step_type"] == "wait"
        assert data["root"]["failure"][0]["step_type"] == "inmail"

    def test_page_loads(self, admin_client):
        resp = admin_client.get("/dashboard/")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.content

    def test_requires_staff(self, client, db):
        resp = client.get("/dashboard/api/kpis/")
        assert resp.status_code in (302, 403)
