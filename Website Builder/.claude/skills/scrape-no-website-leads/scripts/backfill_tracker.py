#!/usr/bin/env python3
"""
Backfill Search Tracker from Google Sheets

Reads all existing leads from the Google Sheet, groups them by
(search_query × source), and writes the inferred search history
to search_coverage.json so smart_scrape.py knows what's already done.

Limitation: we only have the no-website leads (numerator), not the
total businesses checked (denominator). So backfilled records are
flagged with "backfilled": true and their yield rates are excluded
from the smart picker's scoring — they only serve to mark combos
as covered (in cooldown).

Usage:
    python3 backfill_tracker.py
    python3 backfill_tracker.py --dry-run    # preview without writing
    python3 backfill_tracker.py --force      # overwrite existing tracker entries
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from execution.google_auth import get_credentials  # noqa: E402
import gspread
from dotenv import load_dotenv

load_dotenv()

from search_tracker import SearchTracker, _parse_trade_city_from_query, _normalize_key

LEADS_SHEET_ID = os.getenv("LEADS_SHEET_ID", "")
LEADS_SHEET_URL = os.getenv("LEADS_SHEET_URL", "")


def _detect_source(row: dict) -> str:
    """Detect scraping source from a lead row."""
    notes = row.get("notes", "") or ""
    gmaps_url = row.get("google_maps_url", "") or ""
    if notes.startswith("local.ch:") or "local.ch" in notes[:30]:
        return "local.ch"
    if gmaps_url:
        return "google-maps"
    # Fall back: if search_query looks like "X in Y" with Swiss city, assume local.ch
    return "local.ch"


def _normalize_search_query(q: str) -> str:
    """Lowercase and strip the search query for consistent grouping."""
    return (q or "").strip().lower()


def read_sheet_leads() -> list[dict]:
    """Read all lead rows from the Google Sheet."""
    creds = get_credentials()
    client = gspread.authorize(creds)

    sheet = None
    if LEADS_SHEET_URL:
        sheet = client.open_by_url(LEADS_SHEET_URL).sheet1
    elif LEADS_SHEET_ID:
        sheet = client.open_by_key(LEADS_SHEET_ID).sheet1
    else:
        print("ERROR: Set LEADS_SHEET_URL or LEADS_SHEET_ID in .env")
        sys.exit(1)

    print(f"Reading leads from sheet...")
    records = sheet.get_all_records()
    print(f"  Found {len(records)} rows")
    return records


def group_by_search(leads: list[dict]) -> list[dict]:
    """
    Group leads by (normalised_search_query, source) and build
    one tracker record per group.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for lead in leads:
        q = _normalize_search_query(lead.get("search_query", ""))
        if not q:
            continue
        source = _detect_source(lead)
        groups[(q, source)].append(lead)

    records = []
    for (q, source), group_leads in sorted(groups.items()):
        trade_raw, city_raw = _parse_trade_city_from_query(q)
        trade_key = _normalize_key(trade_raw) if trade_raw else ""
        city_key = _normalize_key(city_raw) if city_raw else ""

        # Use earliest scraped_at as the search date
        dates = [l.get("scraped_at", "") for l in group_leads if l.get("scraped_at")]
        searched_at = min(dates) if dates else ""

        records.append({
            "trade": trade_key,
            "city": city_key,
            "source": source,
            "raw_query": q,
            "searched_at": searched_at,
            "businesses_checked": None,   # Unknown for backfilled records
            "no_website_count": len(group_leads),
            "yield_rate": None,           # Cannot compute without businesses_checked
            "backfilled": True,           # Flag: exclude from yield scoring
        })

    return records


def backfill(dry_run: bool = False, force: bool = False):
    leads = read_sheet_leads()
    if not leads:
        print("No leads found in sheet.")
        return

    new_records = group_by_search(leads)
    print(f"\nInferred {len(new_records)} unique search groups from {len(leads)} leads:\n")

    for r in new_records:
        trade = r["trade"] or "?"
        city = r["city"] or "?"
        src = r["source"]
        count = r["no_website_count"]
        date = r["searched_at"][:10] if r["searched_at"] else "unknown date"
        print(f"  {trade:20s} in {city:20s} via {src:12s}  →  {count} leads  [{date}]")

    if dry_run:
        print(f"\n[dry-run] Would write {len(new_records)} records. Use without --dry-run to apply.")
        return

    tracker = SearchTracker()

    if force:
        # Keep existing non-backfilled records, replace all backfilled ones
        tracker.coverage = [r for r in tracker.coverage if not r.get("backfilled")]
        print(f"\nCleared existing backfilled records.")

    # Determine which combos already exist (to avoid duplicating)
    existing = set()
    for r in tracker.coverage:
        existing.add((r.get("trade", ""), r.get("city", ""), r.get("source", "")))

    added = 0
    skipped = 0
    for r in new_records:
        key = (r["trade"], r["city"], r["source"])
        if key in existing and not force:
            skipped += 1
            continue
        tracker.coverage.append(r)
        existing.add(key)
        added += 1

    tracker._save()
    print(f"\nDone. Added {added} records, skipped {skipped} already-tracked combos.")
    print(f"Tracker now has {len(tracker.coverage)} total records.")
    print(f"\nCoverage file: {tracker.coverage_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill search tracker from existing Google Sheets leads",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to tracker")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing backfilled entries")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
