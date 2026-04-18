#!/usr/bin/env python3
"""
No-Website Lead Generation Pipeline — Scrape, Filter & Verify

This script handles the DETERMINISTIC steps of the pipeline:
1. Scrape Google Maps for businesses (via Apify)
2. Filter to only businesses WITHOUT a real website (smart 2-layer filter)
3. Verify by probing candidate domains (catches false positives)

After this script runs, Claude Code uses WebSearch to enrich contacts
(owner name, email, phone, social media) for each verified lead.

Target market: Switzerland & Europe

Usage:
    python3 no_website_pipeline.py --search "Maler in Dietikon" --limit 20
    python3 no_website_pipeline.py --search "Elektriker in Zürich" --limit 50 --deep-check
    python3 no_website_pipeline.py --search "Coiffeur in Bern" --limit 30 --skip-verify
"""

import os
import sys
import json
import argparse
from datetime import datetime

# Add project root to path for shared utilities
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
sys.path.insert(0, PROJECT_ROOT)

from execution.utils import generate_lead_id, stringify_value, parse_address, save_intermediate

# Import sibling scripts
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from scrape_google_maps import scrape_google_maps
from filter_no_website import filter_businesses
from verify_no_website import verify_businesses


def flatten_lead(gmaps_data: dict, contacts: dict, search_query: str) -> dict:
    """
    Flatten Google Maps data + extracted contacts into the 25-column lead schema.

    Args:
        gmaps_data: Raw data from Google Maps scraper.
        contacts: Extracted contact data (from Claude Code extraction).
        search_query: Original search query.

    Returns:
        Flattened dictionary matching LEAD_COLUMNS schema.
    """
    address = gmaps_data.get("address", "")
    addr_parts = parse_address(address)

    # Extract social media from contacts
    social_fb = contacts.get("facebook", "")
    social_ig = contacts.get("instagram", "")
    social_li = contacts.get("linkedin", "")

    # Owner info
    owner_name = contacts.get("owner_name", "")
    owner_email = contacts.get("owner_email", "")
    owner_phone = contacts.get("owner_phone", "")

    # All emails (combine owner + general)
    emails = contacts.get("emails", []) or []
    if owner_email and owner_email not in emails:
        emails.insert(0, owner_email)

    # Generate lead ID
    lead_id = generate_lead_id(
        gmaps_data.get("title", ""),
        address,
    )

    return {
        # Metadata
        "lead_id": lead_id,
        "scraped_at": datetime.now().isoformat(),
        "search_query": search_query,
        # Business Info (from Google Maps)
        "business_name": gmaps_data.get("title", ""),
        "category": gmaps_data.get("categoryName", ""),
        "address": address,
        "city": addr_parts.get("city") or gmaps_data.get("city", ""),
        "state": addr_parts.get("state") or gmaps_data.get("state", ""),
        "zip_code": addr_parts.get("zip_code") or gmaps_data.get("postalCode", ""),
        "phone": gmaps_data.get("phone", ""),
        "google_maps_url": gmaps_data.get("url", ""),
        "rating": str(gmaps_data.get("totalScore", "")),
        "review_count": str(gmaps_data.get("reviewsCount", "")),
        # Contact Info (from Claude Code extraction)
        "owner_name": stringify_value(owner_name),
        "owner_email": stringify_value(owner_email),
        "owner_phone": stringify_value(owner_phone),
        "emails": stringify_value(emails),
        "facebook": stringify_value(social_fb),
        "instagram": stringify_value(social_ig),
        "linkedin": stringify_value(social_li),
        # Pipeline Status (defaults for new leads)
        "status": "new",
        "website_url": "",
        "email_sent_date": "",
        "response_date": "",
        "notes": "",
        # Acquisition tracking
        "acquisition_source": "outreach",
    }


def run_scrape_and_filter(
    search_query: str,
    max_results: int = 20,
    location: str = None,
    workers: int = 5,
    deep_check: bool = False,
    skip_verify: bool = False,
) -> dict:
    """
    Run the deterministic steps: scrape, filter, and verify.

    Steps:
    1. Scrape Google Maps (via Apify)
    2. Filter to no-website businesses (smart 2-layer filter)
    3. Verify by probing candidate domains (catches false positives)

    After this, Claude Code uses WebSearch to enrich contacts, then saves to Sheets.

    Args:
        search_query: What to search on Google Maps (e.g., "Maler in Dietikon")
        max_results: Max businesses to scrape from Maps
        location: Optional location filter
        workers: Parallel workers for domain verification
        deep_check: Use HTTP deep-check in filter (slower, catches more)
        skip_verify: Skip domain verification step

    Returns:
        Dict with pipeline results and file paths.
    """
    results = {
        "search_query": search_query,
        "started_at": datetime.now().isoformat(),
        "businesses_found": 0,
        "no_website_count": 0,
        "verified_count": 0,
        "removed_by_verify": 0,
        "output_file": None,
        "errors": [],
    }

    # =========================================================================
    # STEP 1: Scrape Google Maps
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"STEP 1: Scraping Google Maps for '{search_query}'")
    print(f"{'='*60}")

    businesses = scrape_google_maps(
        search_query=search_query,
        max_results=max_results,
        location=location,
    )

    if not businesses:
        results["errors"].append("No businesses found on Google Maps")
        print("ERROR: No businesses found. Try a different search query or location.")
        return results

    results["businesses_found"] = len(businesses)
    print(f"Found {len(businesses)} businesses")
    save_intermediate(businesses, "gmaps_raw")

    # =========================================================================
    # STEP 2: Smart Filter — keep only businesses WITHOUT real websites
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"STEP 2: Filtering to businesses without real websites")
    print(f"{'='*60}")

    no_website, has_website, filter_stats = filter_businesses(
        businesses, deep_check=deep_check
    )

    results["no_website_count"] = len(no_website)

    print(f"\nFilter results:")
    print(f"  No real website: {len(no_website)} ({filter_stats['hit_rate']}%)")
    print(f"  Has real website: {len(has_website)} (skipped)")
    for reason, count in sorted(filter_stats["reasons"].items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")

    if not no_website:
        results["errors"].append("All businesses already have real websites")
        print("\nNo leads to process — all businesses have real websites.")
        return results

    save_intermediate(no_website, "no_website")

    # =========================================================================
    # STEP 3: Verify — probe candidate domains to catch false positives
    # =========================================================================
    if skip_verify:
        print(f"\n{'='*60}")
        print(f"STEP 3: Skipped (--skip-verify)")
        print(f"{'='*60}")
        verified = no_website
        results["verified_count"] = len(verified)
    else:
        print(f"\n{'='*60}")
        print(f"STEP 3: Verifying {len(no_website)} businesses (domain probe)")
        print(f"{'='*60}")

        verified, removed, verify_stats = verify_businesses(
            no_website, max_workers=workers
        )
        results["verified_count"] = len(verified)
        results["removed_by_verify"] = len(removed)

        print(f"\nVerification results:")
        print(f"  Verified no website: {verify_stats['verified_no_website']}")
        print(f"  Removed (found site): {verify_stats['removed_has_website']} ({verify_stats['removal_rate']}%)")
        print(f"  Domains probed: {verify_stats['total_domains_probed']}")

    if not verified:
        results["errors"].append("All businesses were removed during verification")
        print("\nNo verified leads remaining.")
        return results

    output_file = save_intermediate(verified, "verified_no_website")
    results["output_file"] = output_file

    # Record to search coverage tracker (non-fatal if it fails)
    try:
        from search_tracker import auto_record_google_maps
        auto_record_google_maps(
            search_query=search_query,
            businesses_checked=results["businesses_found"],
            no_website_count=results["verified_count"],
        )
    except Exception:
        pass  # Tracker is non-critical

    # =========================================================================
    # SUMMARY
    # =========================================================================
    results["completed_at"] = datetime.now().isoformat()

    print(f"\n{'='*60}")
    print("SCRAPE, FILTER & VERIFY COMPLETE")
    print(f"{'='*60}")
    print(f"Businesses found on Maps:  {results['businesses_found']}")
    print(f"Without real website:      {results['no_website_count']}")
    print(f"Verified (no website):     {results['verified_count']}")
    if not skip_verify:
        print(f"Removed by verification:   {results['removed_by_verify']}")
    print(f"Output file:               {results['output_file']}")
    print(f"\nNext: Claude Code will use WebSearch to enrich contacts, then save to Google Sheets.")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="No-Website Lead Pipeline — Scrape, Filter & Verify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search (Swiss market)
  python3 no_website_pipeline.py --search "Maler in Dietikon" --limit 20

  # With specific location
  python3 no_website_pipeline.py --search "Elektriker" --location "Zürich" --limit 50

  # Deep check (slower but catches more fake websites)
  python3 no_website_pipeline.py --search "Schreiner in Bern" --limit 100 --deep-check

  # Skip domain verification (faster, less accurate)
  python3 no_website_pipeline.py --search "Coiffeur in Bern" --limit 30 --skip-verify
        """,
    )

    parser.add_argument("--search", required=True, help="Search query for Google Maps")
    parser.add_argument("--limit", type=int, default=20, help="Max businesses to scrape (default: 20)")
    parser.add_argument("--location", help="Optional location to focus search")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers for verification (default: 5)")
    parser.add_argument("--deep-check", action="store_true", help="Use HTTP deep-check in filter")
    parser.add_argument("--skip-verify", action="store_true", help="Skip domain verification step")
    parser.add_argument("--json", action="store_true", help="Output pipeline results as JSON")

    args = parser.parse_args()

    results = run_scrape_and_filter(
        search_query=args.search,
        max_results=args.limit,
        location=args.location,
        workers=args.workers,
        deep_check=args.deep_check,
        skip_verify=args.skip_verify,
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if results["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
