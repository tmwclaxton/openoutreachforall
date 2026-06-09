"""One-off: send pending connection requests NOW at a fixed gap, bypassing the
send window and pacing. Still respects the daily cap (won't exceed it). Use for
a manual top-up; normal sending stays paced inside the window.
"""
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send pending connection requests now, one every --gap seconds (respects the daily cap)."

    def add_arguments(self, parser):
        parser.add_argument("--gap", type=int, default=30, help="seconds between sends")
        parser.add_argument("--count", type=int, default=0, help="max to send (0 = up to the remaining daily cap)")

    def handle(self, *args, **options):
        from linkedin.accounts.limits import cap_for, daily_count, has_capacity
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session
        from linkedin.models import LeadCampaignState
        from linkedin.sequences import executor

        prof = get_first_active_profile()
        if not prof:
            self.stderr.write("No active LinkedIn profile.")
            return

        remaining = cap_for(prof, "connect") - daily_count(prof, "connect")
        budget = options["count"] or remaining
        budget = max(0, min(budget, remaining))  # never exceed the daily cap
        if budget <= 0:
            self.stdout.write("Daily connect cap already reached — nothing to send.")
            return

        states = list(
            LeadCampaignState.objects.filter(
                current_step__step_type="connect",
                awaiting_decision=False,
                state=LeadCampaignState.State.ACTIVE,
            ).select_related("lead", "current_step").order_by("-lead__ai_score")[:budget]
        )
        if not states:
            self.stdout.write("No pending connection-request steps.")
            return

        session = get_or_create_session(prof)
        session.ensure_browser()
        self.stdout.write(f"Flushing up to {len(states)} connection requests, {options['gap']}s apart…")

        sent = 0
        for i, state in enumerate(states):
            if not has_capacity(prof, "connect"):
                self.stdout.write("Daily cap reached — stopping.")
                break
            try:
                # Phase-1 connect send (send + log + move to awaiting-decision),
                # bypassing advance_state's window/pacing gate.
                executor._handle_connect(session, state, state.current_step)
                sent += 1
                self.stdout.write(f"  sent {sent}/{len(states)} → {state.lead.public_identifier}")
            except Exception as exc:
                self.stderr.write(f"  failed {state.lead_id}: {exc!r}")
            if i < len(states) - 1:
                time.sleep(options["gap"])

        self.stdout.write(self.style.SUCCESS(f"Done — {sent} connection requests sent."))
