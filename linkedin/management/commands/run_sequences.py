from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Enroll active sequence campaigns and run one pass of the sequence executor."

    def handle(self, *args, **options):
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session
        from linkedin.models import Campaign
        from linkedin.sequences import executor

        enrolled = 0
        for campaign in Campaign.objects.filter(
            status=Campaign.Status.ACTIVE, sequence__isnull=False, lead_list__isnull=False,
        ):
            enrolled += executor.enroll_campaign(campaign)["enrolled"]
        self.stdout.write(f"Enrolled {enrolled} new lead state(s).")

        profile = get_first_active_profile()
        if profile is None:
            self.stderr.write("No active LinkedIn profile — cannot run sequence actions.")
            return
        session = get_or_create_session(profile)
        advanced = executor.run_due_states(session)
        self.stdout.write(self.style.SUCCESS(f"Sequence executor advanced {advanced} state(s)."))
