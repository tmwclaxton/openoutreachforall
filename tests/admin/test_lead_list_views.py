# tests/admin/test_lead_list_views.py
"""Admin views for LeadList + CSV upload form (M1)."""
from __future__ import annotations

import io

import numpy as np
import pytest
from django.urls import reverse

from tests.factories import UserFactory


@pytest.fixture
def admin_client(db, client):
    from django.contrib.auth.models import User

    user = User.objects.create_superuser("admin", "admin@example.com", "pw")
    client.force_login(user)
    return client


def _list():
    from linkedin.models import LeadList

    return LeadList.objects.create(
        name="L1", owner=UserFactory(), source_type=LeadList.SourceType.CSV,
    )


@pytest.mark.django_db
class TestLeadListAdmin:
    def test_changelist_loads(self, admin_client):
        _list()
        resp = admin_client.get(reverse("admin:linkedin_leadlist_changelist"))
        assert resp.status_code == 200
        assert b"L1" in resp.content

    def test_detail_loads(self, admin_client):
        ll = _list()
        resp = admin_client.get(reverse("admin:linkedin_leadlist_change", args=[ll.pk]))
        assert resp.status_code == 200

    def test_delete_is_forbidden(self, admin_client):
        ll = _list()
        resp = admin_client.get(reverse("admin:linkedin_leadlist_delete", args=[ll.pk]))
        assert resp.status_code in (403, 302)

    def test_csv_upload_form_renders(self, admin_client):
        resp = admin_client.get(reverse("admin:linkedin_leadlist_import_csv"))
        assert resp.status_code == 200
        assert b"csv_file" in resp.content

    def test_csv_upload_creates_list_and_leads(self, admin_client):
        from crm.models import Lead
        from linkedin.models import LeadList

        content = "linkedin_url\nhttps://www.linkedin.com/in/alice/\nhttps://www.linkedin.com/in/bob/\n"
        upload = io.BytesIO(content.encode("utf-8"))
        upload.name = "leads.csv"
        resp = admin_client.post(
            reverse("admin:linkedin_leadlist_import_csv"),
            {"name": "Uploaded", "csv_file": upload},
            follow=True,
        )
        assert resp.status_code == 200
        ll = LeadList.objects.get(name="Uploaded")
        assert Lead.objects.filter(lead_list=ll).count() == 2


@pytest.mark.django_db
class TestLeadAdminEnrichmentFilter:
    def test_filter_by_enrichment_status(self, admin_client):
        from crm.models import Lead

        Lead.objects.create(
            linkedin_url="https://www.linkedin.com/in/alice/",
            public_identifier="alice",
            embedding=np.ones(384, dtype=np.float32).tobytes(),
        )
        Lead.objects.create(
            linkedin_url="https://www.linkedin.com/in/bob/", public_identifier="bob",
        )
        url = reverse("admin:crm_lead_changelist")
        enriched = admin_client.get(url + "?enriched=yes")
        assert enriched.status_code == 200
        assert b"alice" in enriched.content
        assert b"bob" not in enriched.content
