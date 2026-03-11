#!/usr/bin/env python3
"""
Smart filter to identify businesses WITHOUT a real website.

Two-layer filtering:
  Layer 1 (fast): Domain blocklist — catches directory listings (local.ch),
                  social media (facebook.com), and review sites (google.com).
  Layer 2 (optional): HTTP validation — fetches the URL to check for redirects
                  to directory sites or placeholder pages.

A business is considered to have NO real website if:
  - The website field is empty/null
  - The website URL points to a known directory or social media site
  - (With --deep-check) The website redirects to a directory site

Usage:
    python3 filter_no_website.py --input .tmp/gmaps_raw.json --output .tmp/no_website.json
    python3 filter_no_website.py --input .tmp/gmaps_raw.json --output .tmp/no_website.json --deep-check
"""

import os
import sys
import json
import argparse
from urllib.parse import urlparse

# =============================================================================
# LAYER 1: Domain Blocklist
# =============================================================================
# If a business's "website" URL domain matches any of these, it's NOT a real
# business website — it's a directory listing, social media page, or review site.
#
# Focused on Swiss/European market (primary target) + global platforms.
# To add more domains: just append to the relevant section below.
# =============================================================================

DIRECTORY_DOMAINS = [
    # --- Swiss directories (PRIMARY target market) ---
    "local.ch",
    "search.ch",
    "tel.search.ch",
    "directories.ch",
    "yelu.ch",
    "klara.ch",
    "localsearch.ch",
    "zip.ch",
    "eintraege.ch",
    "firmendb.ch",
    "moneyhouse.ch",
    "guidle.com",
    "branchenbuch.ch",
    "swissguide.ch",
    # --- Swiss trade/industry portals (list entire professions, not individual businesses) ---
    "coiffeur.ch",
    "coiffeuse.ch",
    "maler.ch",
    "schreiner.ch",
    "schreinerei.ch",
    "elektriker.ch",
    "sanitaer.ch",
    "gaertner.ch",
    "gaertnerei.ch",
    "reinigung.ch",
    "handwerker.ch",
    "stadtgaertnerei.ch",
    # --- German directories ---
    "gelbeseiten.de",
    "dasoertliche.de",
    "11880.com",
    "meinestadt.de",
    "branchenbuch.meinestadt.de",
    "golocal.de",
    "kennstdueinen.de",
    "werkenntdenbesten.de",
    # --- Austrian directories ---
    "herold.at",
    "gelbeseiten.at",
    # --- French directories ---
    "pagesjaunes.fr",
    "118712.fr",
    # --- Italian directories ---
    "paginegialle.it",
    # --- Pan-European ---
    "europages.com",
    "cylex.com",
    "cylex.ch",
    "cylex.de",
    "hotfrog.com",
    "hotfrog.ch",
    "hotfrog.de",
    "tupalo.com",
    "tupalo.net",
    "kompass.com",
    "infobel.com",
    # --- Global directories ---
    "yelp.com",
    "yelp.ch",
    "yelp.de",
    "yelp.fr",
    "yellowpages.com",
    "bbb.org",
    "manta.com",
    "foursquare.com",
    # --- Social media ---
    "facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
    "xing.com",
    # --- Review / maps sites ---
    "tripadvisor.com",
    "tripadvisor.ch",
    "tripadvisor.de",
    "trustpilot.com",
    "google.com",
    "google.ch",
    "google.de",
    "google.fr",
    "maps.google.com",
    # --- Booking / marketplace ---
    "booking.com",
    "airbnb.com",
    "tutti.ch",
    "anibis.ch",
    "ricardo.ch",
    "jobs.ch",
    "immoscout24.ch",
    "homegate.ch",
    "comparis.ch",
    "thumbtack.com",
    "homeadvisor.com",
    "angi.com",
    "nextdoor.com",
    # --- Swiss handwerker / service marketplaces ---
    "renovero.ch",
    "handwerkersuche.ch",
    "houzy.ch",
    "pricehubble.com",
    "localsearch.ch",
    "klaro.ch",
]

# Build a set of normalized domains for fast lookup
_BLOCKLIST = set()
for domain in DIRECTORY_DOMAINS:
    _BLOCKLIST.add(domain.lower())
    # Also add www. variant
    if not domain.startswith("www."):
        _BLOCKLIST.add(f"www.{domain.lower()}")


def _extract_domain(url: str) -> str:
    """Extract the domain (without www.) from a URL."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove port number if present
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain
    except Exception:
        return ""


def _domain_matches_blocklist(domain: str) -> bool:
    """Check if a domain (or any parent domain) is in the blocklist."""
    if not domain:
        return False

    # Direct match
    if domain in _BLOCKLIST:
        return True

    # Check parent domains (e.g., "en.local.ch" → "local.ch")
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in _BLOCKLIST:
            return True

    return False


def is_valid_url(url: str) -> bool:
    """
    Check if a URL string is actually a real URL (not just 'http://' or whitespace).

    Args:
        url: URL string to validate.

    Returns:
        True if the URL appears to be a real, navigable address.
    """
    if not url or not url.strip():
        return False
    url = url.strip()
    # Strip protocol and check if there's a real domain
    for prefix in ["https://", "http://"]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Remove trailing slashes
    url = url.strip("/")
    # Must have at least one dot (domain.tld) and some length
    return bool(url) and "." in url and len(url) > 3


def is_directory_or_social(url: str) -> tuple[bool, str]:
    """
    Check if a URL points to a directory listing or social media page.

    Args:
        url: Website URL to check.

    Returns:
        Tuple of (is_fake, reason).
        - is_fake=True means this is NOT a real business website.
        - reason explains why (e.g., "directory: local.ch", "social: facebook.com").
    """
    if not url or not is_valid_url(url):
        return True, "no_url"

    domain = _extract_domain(url)
    if not domain:
        return True, "invalid_url"

    if _domain_matches_blocklist(domain):
        # Determine category for the reason string
        domain_clean = domain.lstrip("www.")
        if any(s in domain_clean for s in ["facebook", "fb.", "instagram", "twitter", "x.com",
                                            "linkedin", "tiktok", "youtube", "pinterest", "xing"]):
            return True, f"social: {domain_clean}"
        elif any(s in domain_clean for s in ["google", "tripadvisor", "trustpilot"]):
            return True, f"review_site: {domain_clean}"
        elif any(s in domain_clean for s in ["booking", "airbnb", "tutti", "ricardo",
                                              "thumbtack", "homeadvisor", "angi"]):
            return True, f"marketplace: {domain_clean}"
        else:
            return True, f"directory: {domain_clean}"

    return False, "real_website"


def has_real_website(business: dict) -> tuple[bool, str]:
    """
    Determine if a business has a real, owned website.

    Args:
        business: Business dict from Google Maps scraper (must have 'website' key).

    Returns:
        Tuple of (has_website, reason).
        - has_website=True means this business has its own website (skip it).
        - has_website=False means this is a target (no real website).
    """
    website = business.get("website", "")

    # No website field at all
    if not website or not website.strip():
        return False, "no_website_listed"

    # Check against blocklist
    is_fake, reason = is_directory_or_social(website)
    if is_fake:
        return False, reason

    # Has a real website
    return True, "real_website"


def filter_businesses(
    businesses: list[dict],
    deep_check: bool = False,
) -> tuple[list[dict], list[dict], dict]:
    """
    Filter businesses to only those without real websites.

    Args:
        businesses: List of business dicts from Google Maps scraper.
        deep_check: If True, fetch URLs to check for redirects (slower).

    Returns:
        Tuple of (no_website, has_website, stats).
        - no_website: Businesses that are targets (no real website).
        - has_website: Businesses that already have a real website (skipped).
        - stats: Dict with filtering statistics.
    """
    no_website = []
    has_website = []
    reasons = {}

    for business in businesses:
        has_site, reason = has_real_website(business)

        if has_site:
            has_website.append(business)
        else:
            # Tag the business with why it was selected
            business["_filter_reason"] = reason
            no_website.append(business)

        # Track stats
        reasons[reason] = reasons.get(reason, 0) + 1

    # Optional Layer 2: HTTP deep check
    if deep_check and has_website:
        print(f"  Deep-checking {len(has_website)} websites for redirects...")
        rechecked_has = []
        for business in has_website:
            is_actually_fake = _deep_check_url(business.get("website", ""))
            if is_actually_fake:
                business["_filter_reason"] = "redirect_to_directory"
                no_website.append(business)
                reasons["redirect_to_directory"] = reasons.get("redirect_to_directory", 0) + 1
            else:
                rechecked_has.append(business)
        has_website = rechecked_has

    stats = {
        "total": len(businesses),
        "no_website": len(no_website),
        "has_website": len(has_website),
        "hit_rate": round(len(no_website) / len(businesses) * 100, 1) if businesses else 0,
        "reasons": reasons,
    }

    return no_website, has_website, stats


def _deep_check_url(url: str) -> bool:
    """
    Fetch a URL and check if it redirects to a directory/social site.
    Returns True if the final destination is a blocked domain.

    This is Layer 2 — only used with --deep-check flag.
    """
    try:
        import httpx

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            response = client.head(url, headers=headers)
            final_url = str(response.url)
            final_domain = _extract_domain(final_url)
            return _domain_matches_blocklist(final_domain)
    except Exception:
        # On error, assume it's a real website (conservative)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Filter Google Maps businesses to only those without real websites"
    )
    parser.add_argument("--input", required=True, help="Input JSON file (from scrape_google_maps.py)")
    parser.add_argument("--output", default=None, help="Output JSON file (default: auto in .tmp/)")
    parser.add_argument(
        "--deep-check",
        action="store_true",
        help="Fetch URLs to check for redirects to directory sites (slower, more accurate)",
    )
    parser.add_argument("--json", action="store_true", help="Output filtered results as JSON to stdout")

    args = parser.parse_args()

    # Load input
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            businesses = json.load(f)
    except Exception as e:
        print(f"Error loading {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(businesses)} businesses from {args.input}")

    # Filter
    no_website, has_website, stats = filter_businesses(businesses, deep_check=args.deep_check)

    # Print summary
    print(f"\n{'='*60}")
    print(f"FILTER RESULTS")
    print(f"{'='*60}")
    print(f"Total businesses:   {stats['total']}")
    print(f"No real website:    {stats['no_website']} ({stats['hit_rate']}%)")
    print(f"Has real website:   {stats['has_website']}")
    print(f"\nBreakdown:")
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    # Save output
    if args.json:
        print(json.dumps(no_website, indent=2, ensure_ascii=False))
    else:
        if args.output:
            output_file = args.output
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
        else:
            from datetime import datetime

            os.makedirs(".tmp", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f".tmp/no_website_{timestamp}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(no_website, f, indent=2, ensure_ascii=False)

        print(f"\nFiltered results saved to {output_file}")

    return no_website, has_website, stats


if __name__ == "__main__":
    main()
