# tests/db/test_lead_list.py
"""LeadList model + CSV import (manual lead import, M1)."""
from __future__ import annotations

import io

import pytest

from tests.factories import UserFactory


def _csv(*lines: str) -> io.StringIO:
    return io.StringIO("\n".join(["linkedin_url", *lines]))


@pytest.mark.django_db
class TestLeadListModel:
    def test_create_and_str(self):
        from linkedin.models import LeadList

        ll = LeadList.objects.create(
            name="Q3 Founders", owner=UserFactory(), source_type=LeadList.SourceType.CSV,
        )
        assert str(ll) == "Q3 Founders"
        assert ll.is_archived is False

    def test_archive_is_soft_delete(self):
        from linkedin.models import LeadList

        ll = LeadList.objects.create(
            name="L", owner=UserFactory(), source_type=LeadList.SourceType.MANUAL,
        )
        ll.archive()
        ll.refresh_from_db()
        assert ll.archived_at is not None
        assert ll.is_archived is True
        assert "(Archived)" in str(ll)
        # Row is retired, never removed.
        assert LeadList.objects.filter(pk=ll.pk).exists()

    def test_archive_is_idempotent(self):
        from linkedin.models import LeadList

        ll = LeadList.objects.create(
            name="L", owner=UserFactory(), source_type=LeadList.SourceType.MANUAL,
        )
        ll.archive()
        first = ll.archived_at
        ll.archive()
        ll.refresh_from_db()
        assert ll.archived_at == first


@pytest.mark.django_db
class TestCsvImport:
    def _list(self):
        from linkedin.models import LeadList

        return LeadList.objects.create(
            name="L", owner=UserFactory(), source_type=LeadList.SourceType.CSV,
        )

    def test_imports_rows_and_links_to_list(self):
        from crm.models import Lead
        from linkedin.leads import importer

        ll = self._list()
        result = importer.import_csv(ll, _csv(
            "https://www.linkedin.com/in/alice/",
            "https://www.linkedin.com/in/bob/",
        ))
        assert result == {"created": 2, "skipped": 0, "invalid": 0}
        assert Lead.objects.filter(lead_list=ll).count() == 2
        assert set(Lead.objects.values_list("public_identifier", flat=True)) == {"alice", "bob"}

    def test_imports_25_rows_no_duplicates(self):
        from crm.models import Lead
        from linkedin.leads import importer

        ll = self._list()
        rows = [f"https://www.linkedin.com/in/person-{i}/" for i in range(25)]
        result = importer.import_csv(ll, _csv(*rows))
        assert result["created"] == 25
        assert result["skipped"] == 0
        assert Lead.objects.filter(lead_list=ll).count() == 25

    def test_dedup_within_file(self):
        from linkedin.leads import importer

        result = importer.import_csv(self._list(), _csv(
            "https://www.linkedin.com/in/alice/",
            "https://www.linkedin.com/in/alice/",
        ))
        assert result["created"] == 1
        assert result["skipped"] == 1

    def test_dedup_against_existing_lead(self):
        from crm.models import Lead
        from linkedin.leads import importer

        Lead.objects.create(
            linkedin_url="https://www.linkedin.com/in/alice/", public_identifier="alice",
        )
        result = importer.import_csv(self._list(), _csv("https://www.linkedin.com/in/alice/"))
        assert result["created"] == 0
        assert result["skipped"] == 1
        assert Lead.objects.filter(public_identifier="alice").count() == 1

    def test_invalid_rows_counted(self):
        from linkedin.leads import importer

        result = importer.import_csv(self._list(), _csv("not-a-linkedin-url", "https://example.com/x"))
        assert result["created"] == 0
        assert result["invalid"] == 2

    def test_blank_rows_are_skipped(self):
        from linkedin.leads import importer

        # csv.DictReader skips truly-empty lines; nothing is created or flagged.
        result = importer.import_csv(self._list(), _csv("https://www.linkedin.com/in/alice/", ""))
        assert result == {"created": 1, "skipped": 0, "invalid": 0}

    def test_missing_required_column_raises(self):
        from linkedin.leads import importer

        with pytest.raises(ValueError):
            importer.import_csv(self._list(), io.StringIO("wrong_header\nfoo\n"))
