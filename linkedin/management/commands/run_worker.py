import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Browser worker: reply polling + queued lead searches (owns the LinkedIn session)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=120)

    def handle(self, *args, **options):
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session
        from linkedin.inbox.poller import poll_replies
        from linkedin.leads.importer import process_pending_searches
        from linkedin.sequences.executor import run_due_states

        profile = get_first_active_profile()
        if not profile:
            self.stderr.write("No active LinkedIn profile.")
            return
        session = get_or_create_session(profile)
        self.stdout.write(self.style.SUCCESS(f"worker started for {profile.linkedin_username}"))

        interval = options["interval"]
        while True:
            from django.db import connection

            # Drop the cached connection so each cycle sees rows committed by the
            # web process (e.g. a freshly queued search).
            connection.close()
            try:
                # Poll FIRST so a reply flips the lead to stopped_reply before the
                # executor would otherwise fire its follow-up.
                stopped = poll_replies(session)
                executed = run_due_states(session)
                searched = process_pending_searches(session)
                self.stdout.write(
                    f"cycle: replies_stopped={stopped} executed={executed} searches={searched}", ending="\n",
                )
            except Exception as exc:  # keep the worker alive across transient errors
                self.stderr.write(f"cycle error: {exc!r}"[:200])
            time.sleep(interval)
