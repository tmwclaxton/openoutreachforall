from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a LeadList and import leads from a CSV file or a LinkedIn people-search URL."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Name for the new LeadList.")
        parser.add_argument("--source", choices=["csv", "search_url"], required=True)
        parser.add_argument("--file", help="CSV path (required for --source csv).")
        parser.add_argument("--url", help="People-search URL (required for --source search_url).")
        parser.add_argument("--owner", help="Owner username (defaults to first superuser).")
        parser.add_argument("--cap", type=int, default=None, help="Max leads for search import.")

    def handle(self, *args, **options):
        from linkedin.leads import importer
        from linkedin.models import LeadList

        owner = self._resolve_owner(options.get("owner"))
        source = options["source"]

        if source == "csv":
            path = options.get("file")
            if not path:
                raise CommandError("--file is required for --source csv")
            lead_list = importer.create_lead_list(
                name=options["name"], owner=owner, source_type=LeadList.SourceType.CSV,
            )
            with open(path, newline="", encoding="utf-8") as fh:
                result = importer.import_csv(lead_list, fh)
            self.stdout.write(self.style.SUCCESS(
                f"LeadList '{lead_list.name}' (#{lead_list.pk}): created={result['created']} "
                f"skipped={result['skipped']} invalid={result['invalid']}"
            ))
            return

        url = options.get("url")
        if not url:
            raise CommandError("--url is required for --source search_url")
        lead_list = importer.create_lead_list(
            name=options["name"], owner=owner,
            source_type=LeadList.SourceType.SEARCH_URL, source_url=url,
        )
        session = self._open_session()
        cap = options.get("cap") or importer.SEARCH_IMPORT_CAP
        result = importer.import_search_url(session, lead_list, url, cap=cap)
        self.stdout.write(self.style.SUCCESS(
            f"LeadList '{lead_list.name}' (#{lead_list.pk}): "
            f"created={result['created']} scraped={result['scraped']}"
        ))

    def _resolve_owner(self, username):
        from django.contrib.auth.models import User

        if username:
            owner = User.objects.filter(username=username).first()
            if not owner:
                raise CommandError(f"No user '{username}'")
            return owner
        owner = (
            User.objects.filter(is_superuser=True).order_by("pk").first()
            or User.objects.order_by("pk").first()
        )
        if not owner:
            raise CommandError("No users exist — create one first")
        return owner

    def _open_session(self):
        from linkedin.browser.registry import get_first_active_profile, get_or_create_session

        profile = get_first_active_profile()
        if profile is None:
            raise CommandError("No active LinkedIn profile — onboard one first")
        return get_or_create_session(profile)
