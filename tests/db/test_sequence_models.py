# tests/db/test_sequence_models.py
"""Sequence + SequenceStep tree integrity (M2)."""
from __future__ import annotations

import pytest

from tests.factories import UserFactory


@pytest.mark.django_db
class TestSequenceModels:
    def test_root_step_and_archive(self):
        from linkedin.models import Sequence, SequenceStep as S

        seq = Sequence.objects.create(name="Seq", owner=UserFactory())
        root = S.objects.create(sequence=seq, branch=S.Branch.ROOT, step_type=S.StepType.CONNECT)
        assert seq.root_step == root
        assert seq.archived_at is None
        seq.archive()
        seq.refresh_from_db()
        assert seq.archived_at is not None
        assert "(Archived)" in str(seq)
        # Soft-delete: rows persist.
        assert Sequence.objects.filter(pk=seq.pk).exists()

    def test_branch_children_resolve(self):
        from linkedin.models import Sequence, SequenceStep as S

        seq = Sequence.objects.create(name="Seq", owner=UserFactory())
        connect = S.objects.create(sequence=seq, branch=S.Branch.ROOT, step_type=S.StepType.CONNECT)
        accepted = S.objects.create(sequence=seq, parent=connect, branch=S.Branch.SUCCESS, step_type=S.StepType.WAIT)
        not_accepted = S.objects.create(sequence=seq, parent=connect, branch=S.Branch.FAILURE, step_type=S.StepType.INMAIL)

        assert connect.next_step(S.Branch.SUCCESS) == accepted
        assert connect.next_step(S.Branch.FAILURE) == not_accepted
        # A leaf has no children on either branch.
        assert accepted.next_step(S.Branch.SUCCESS) is None
        assert not_accepted.next_step(S.Branch.FAILURE) is None
