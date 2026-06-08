# linkedin/leads/importer.py
"""Manual lead import — CSV files and LinkedIn people-search URLs.

The manual counterpart to AI auto-discovery: leads are created and attached
to a ``LeadList``. Dedup is by ``public_identifier`` (derived from the
LinkedIn URL), both within the input and against existing ``Lead`` rows.
"""
from __future__ import annotations

import csv as _csv
import logging
from typing import IO
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from linkedin_cli.url_utils import public_id_to_url, url_to_public_id

logger = logging.getLogger(__name__)

# LinkedIn People search exposes ~100 pages of ~10 results; 1000 is the ceiling.
SEARCH_IMPORT_CAP = 1000

CSV_REQUIRED_COLUMN = "linkedin_url"


def create_lead_list(name, owner, source_type, source_url=None):
    """Create and return a new LeadList."""
    from linkedin.models import LeadList

    return LeadList.objects.create(
        name=name,
        owner=owner,
        source_type=source_type,
        source_url=source_url or None,
    )


def import_csv(lead_list, fileobj: IO[str]) -> dict:
    """Create Leads from CSV rows and attach them to ``lead_list``.

    Required column: ``linkedin_url``. Dedup by ``public_identifier`` against
    both the file itself and existing Leads. Optional name/company/title/notes
    columns are accepted but not persisted (no Lead fields for them yet).
    Returns ``{"created", "skipped", "invalid"}``.
    """
    from crm.models import Lead

    reader = _csv.DictReader(fileobj)
    if reader.fieldnames is None or CSV_REQUIRED_COLUMN not in reader.fieldnames:
        raise ValueError(f"CSV must have a '{CSV_REQUIRED_COLUMN}' column")

    created = skipped = invalid = 0
    seen: set[str] = set()
    for row in reader:
        url = (row.get(CSV_REQUIRED_COLUMN) or "").strip()
        public_id = url_to_public_id(url) if url else None
        if not public_id:
            invalid += 1
            continue
        if public_id in seen:
            skipped += 1
            continue
        seen.add(public_id)
        if Lead.objects.filter(public_identifier=public_id).exists():
            skipped += 1
            continue
        Lead.objects.create(
            linkedin_url=public_id_to_url(public_id),
            public_identifier=public_id,
            lead_list=lead_list,
            first_name=(row.get("first_name") or "").strip(),
            last_name=(row.get("last_name") or "").strip(),
            company=(row.get("company") or "").strip(),
        )
        created += 1

    logger.info(
        "CSV import into %s: created=%d skipped=%d invalid=%d",
        lead_list, created, skipped, invalid,
    )
    return {"created": created, "skipped": skipped, "invalid": invalid}


def _with_page(url: str, page: int) -> str:
    """Return ``url`` with its ``page`` query parameter set to ``page``."""
    parts = urlparse(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["page"] = [str(page)]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def scrape_search_url(session, url: str, cap: int = SEARCH_IMPORT_CAP) -> list[str]:
    """Return up to ``cap`` unique profile URLs from a people-search URL.

    Paginates via the ``page`` query parameter, reusing ``linkedin_cli``'s
    page navigation and ``/in/`` extraction. Stops when a page yields no new
    URLs or the cap is reached.
    """
    from linkedin_cli.browser.nav import extract_in_urls, goto_page

    session.ensure_browser()
    expected = urlparse(url).path.rstrip("/") or "/"
    collected: list[str] = []
    seen: set[str] = set()
    page_num = 1
    while len(collected) < cap:
        page_url = _with_page(url, page_num)
        goto_page(
            session,
            action=lambda u=page_url: session.page.goto(u),
            expected_url_pattern=expected,
            error_message="Failed to reach search results",
        )
        fresh = [u for u in extract_in_urls(session.page) if u not in seen]
        if not fresh:
            break
        for u in fresh:
            seen.add(u)
            collected.append(u)
            if len(collected) >= cap:
                break
        page_num += 1

    return collected[:cap]


def import_search_url(session, lead_list, url: str, cap: int = SEARCH_IMPORT_CAP) -> dict:
    """Scrape a people-search URL and enrich up to ``cap`` new leads into
    ``lead_list``. Idempotent: re-running the same URL skips existing leads.
    Returns ``{"created", "scraped"}``.
    """
    from linkedin.db.leads import create_enriched_lead, lead_exists
    from linkedin_cli.api.client import PlaywrightLinkedinAPI

    scraped = scrape_search_url(session, url, cap=cap)
    new_urls = [u for u in scraped if not lead_exists(u)][:cap]

    session.ensure_browser()
    api = PlaywrightLinkedinAPI(session=session)
    created = 0
    for profile_url in new_urls:
        try:
            profile, _raw = api.get_profile(profile_url=profile_url)
        except Exception:
            logger.warning("Voyager failed for %s — skipping", profile_url)
            continue
        if not profile:
            continue
        if create_enriched_lead(session, profile_url, profile, lead_list=lead_list) is not None:
            created += 1

    logger.info(
        "Search import into %s: created=%d (scraped=%d)", lead_list, created, len(scraped),
    )
    return {"created": created, "scraped": len(scraped)}


def process_pending_searches(session, cap: int = SEARCH_IMPORT_CAP) -> list:
    """Scrape any lead lists queued via the dashboard search box. Clears the
    ``pending_search`` flag whether or not the scrape succeeds. Returns
    ``[(list_id, created), ...]``.
    """
    from linkedin.models import LeadList

    results = []
    for ll in LeadList.objects.filter(pending_search=True, archived_at__isnull=True):
        try:
            r = import_search_url(session, ll, ll.source_url or "", cap=cap)
            results.append((ll.pk, r.get("created", 0)))
        except Exception:
            logger.exception("Pending search failed for list %s", ll.pk)
            results.append((ll.pk, 0))
        finally:
            ll.pending_search = False
            ll.save(update_fields=["pending_search"])
    return results
