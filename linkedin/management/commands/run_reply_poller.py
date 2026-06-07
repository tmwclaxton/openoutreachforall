from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Poll active sequence leads for replies; stop any lead that answered."

    def handle(self, *args, **options):
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session
        from linkedin.inbox.poller import poll_replies

        profile = get_first_active_profile()
        if profile is None:
            self.stderr.write("No active LinkedIn profile.")
            return
        session = get_or_create_session(profile)
        stopped = poll_replies(session)
        self.stdout.write(self.style.SUCCESS(f"Reply poller stopped {stopped} sequence(s)."))
