"""One-off/idempotent: create `connect_accepted` ActionLog events for leads who
have already accepted (derived from being past the connect step on its accepted
branch) but predate acceptance-event recording. Makes the activity feed show who
accepted and when, consistently with the derived Accepted count.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill connect_accepted events for already-accepted leads (idempotent)."

    def handle(self, *args, **options):
        from linkedin.models import (
            ActionLog, Campaign, LeadCampaignState, LinkedInProfile, SequenceStep,
        )

        fallback_account = LinkedInProfile.objects.filter(active=True).first() or LinkedInProfile.objects.first()
        created = 0
        for c in Campaign.objects.filter(sequence__isnull=False).select_related("sequence"):
            root = c.sequence.root_step if c.sequence_id else None
            if not root or root.step_type != SequenceStep.StepType.CONNECT:
                continue
            ids, stack = set(), list(root.children.filter(branch=SequenceStep.Branch.SUCCESS))
            while stack:
                s = stack.pop()
                ids.add(s.id)
                stack.extend(list(s.children.all()))
            if not ids:
                continue
            states = LeadCampaignState.objects.filter(
                campaign=c, current_step_id__in=ids,
            ).select_related("lead")
            for st in states:
                if ActionLog.objects.filter(
                    campaign=c, lead=st.lead, action_type=ActionLog.ActionType.CONNECT_ACCEPTED,
                ).exists():
                    continue
                thread = st.lead.threads.first()
                account = (thread.account if thread else None) or fallback_account
                if account is None:
                    continue
                log = ActionLog.objects.create(
                    linkedin_profile=account, campaign=c, lead=st.lead,
                    action_type=ActionLog.ActionType.CONNECT_ACCEPTED,
                )
                # Stamp it ~when the lead actually progressed past the connect.
                when = st.last_action_at or st.created_at
                if when:
                    ActionLog.objects.filter(pk=log.pk).update(created_at=when)
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Backfilled {created} connect_accepted events."))
