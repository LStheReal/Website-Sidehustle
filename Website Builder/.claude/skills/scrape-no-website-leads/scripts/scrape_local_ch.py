#!/usr/bin/env python3
"""
Scrape local.ch for businesses WITHOUT websites — direct HTTP scraper.

Scrapes local.ch search results directly (no Apify needed).
For each listing, visits the detail page to check if a real website is listed.
Businesses with no website (or only directory/social links) are kept as leads.

Usage:
    python3 scrape_local_ch.py --query "maler" --city "zuerich" --limit 50
    python3 scrape_local_ch.py --search-url "https://www.local.ch/de/q/zuerich/maler" --limit 50
"""

import os
import sys
import json
import re
import argparse
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote

# Add project root for shared utils
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..", "..", "..", "..")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPT_DIR)

from execution.utils import save_intermediate, generate_lead_id, parse_address, stringify_value
from filter_no_website import _domain_matches_blocklist, _extract_domain

BASE_URL = "https://www.local.ch"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}

# Domains to ignore when looking for website links
IGNORE_DOMAINS = {
    # local.ch infrastructure
    "local.ch", "www.local.ch",
    "localsearch.ch", "profile.localsearch.ch",
    "swissmadesoftware.org",
    "cc.localsearch.ch",
    # Swiss marketplaces / directories (not real business websites)
    "renovero.ch", "www.renovero.ch",
    "houzy.ch",
    "localcities.ch", "www.localcities.ch",
    "hairlist.ch", "www.hairlist.ch",   # hairdresser booking platform
    "trehs.ch",   # Swiss trade directory
    # Messaging apps (not websites)
    "wa.me",   # WhatsApp
    "t.me",    # Telegram
}


def _get_http_client():
    try:
        import httpx
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
        import httpx
    return httpx


def _get_soup(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
        from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _build_search_url(query: str, city: str, language: str = "de", page: int = 1) -> str:
    """Build a local.ch search URL."""
    q = quote(query.lower().replace(" ", "-"))
    c = quote(city.lower().replace(" ", "-").replace("ü", "ue").replace("ä", "ae").replace("ö", "oe"))
    url = f"{BASE_URL}/{language}/q/{c}/{q}"
    if page > 1:
        url += f"?page={page}"
    return url


def _scrape_listing_page(url: str, client) -> list[dict]:
    """
    Scrape one local.ch search results page.
    Returns list of dicts with {name, detail_url, address_hint}.
    """
    try:
        r = client.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
        if r.status_code != 200:
            return []
        soup = _get_soup(r.text)

        # Find all mobile listing elements (dedup with desktop)
        items = soup.find_all(attrs={"data-testid": re.compile(r"^list-element-mobile-")})

        businesses = []
        seen_urls = set()

        for item in items:
            # Get detail page link
            detail_links = [
                a["href"] for a in item.find_all("a", href=True)
                if "/de/d/" in a.get("href", "") or "/fr/d/" in a.get("href", "") or "/it/d/" in a.get("href", "")
            ]
            if not detail_links:
                continue

            detail_url = detail_links[0]
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            # Extract name — try h2/h3 first, then find distinctive text
            name_el = item.find("h2") or item.find("h3") or item.find(attrs={"class": re.compile(r"name|title|heading|firm", re.I)})
            if name_el:
                name = name_el.get_text(strip=True)
            else:
                # Fallback: look for text that's distinctive (not status/rating/time/address text)
                text_parts = [t.strip() for t in item.get_text(" | ").split(" | ") if t.strip()]
                SKIP_WORDS = {"Geöffnet", "Geschlossen", "Offen", "Uhr", "Stern", "Bewertung",
                              "Bewertungen", "Noch", "keine", "nach", "Vereinbarung", "nach", "von"}
                name = ""
                for part in text_parts:
                    # Skip if it's a status word, rating, time, or too short
                    if (len(part) > 4
                            and not re.match(r'^[\d.,/\s]+$', part)
                            and not any(sw in part for sw in {"Stern", "Uhr", "Bewertung", "bis ", "von 5"})
                            and part not in SKIP_WORDS):
                        name = part
                        break

            # Address hint — text with postal code
            address = ""
            for el in item.find_all(["span", "p", "div", "address"]):
                t = el.get_text(strip=True)
                if re.search(r"\d{4}", t) and len(t) < 150:
                    address = t
                    break

            businesses.append({
                "name": name or "Unknown",
                "detail_url": detail_url,
                "address_hint": address,
            })

        return businesses

    except Exception as e:
        print(f"  Warning: Failed to scrape {url}: {e}")
        return []


def _scrape_detail_page(business: dict, client) -> dict | None:
    """
    Visit a local.ch detail page to get phone, website, email, full address.
    Returns None if scraping fails.
    """
    detail_url = business["detail_url"]
    full_url = urljoin(BASE_URL, detail_url)

    try:
        r = client.get(full_url, headers=HEADERS, follow_redirects=True, timeout=10)
        if r.status_code != 200:
            return None

        soup = _get_soup(r.text)
        full_text = soup.get_text(" ", strip=True)

        # Extract website — external links that aren't directory/local.ch
        external_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            domain = _extract_domain(href)
            base_domain = domain.lstrip("www.")
            if base_domain in IGNORE_DOMAINS:
                continue
            if _domain_matches_blocklist(domain):
                continue  # It's a directory link, not their website
            external_links.append(href)

        # Extract phone
        phones = re.findall(r"\+41\s?[\d\s]{9,}|\b0\d\d\s?[\d\s]{6,}", full_text)
        phone = phones[0].strip().replace("  ", " ") if phones else ""

        # Extract email
        emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", full_text)
        # Filter out @local.ch and system emails
        emails = [e for e in emails if "local.ch" not in e and "localsearch" not in e]

        # Extract address — look for postal code pattern
        address = business.get("address_hint", "")
        addr_match = re.search(r"([^,\n]{5,}),?\s+(\d{4})\s+(\w[\w\s-]+)", full_text[:2000])
        if addr_match:
            address = f"{addr_match.group(1)}, {addr_match.group(2)} {addr_match.group(3)}"

        # Extract city from URL: /de/d/{city}/
        city_match = re.search(r"/de/d/([^/]+)/", detail_url)
        city = city_match.group(1).replace("-", " ").title() if city_match else ""

        # Extract zip from address
        zip_match = re.search(r"\b(\d{4})\b", address)
        zip_code = zip_match.group(1) if zip_match else ""

        return {
            "name": business["name"],
            "detail_url": full_url,
            "website": external_links[0] if external_links else "",
            "all_external": external_links[:3],
            "phone": phone,
            "email": emails[0] if emails else "",
            "address": address,
            "city": city,
            "zip_code": zip_code,
        }

    except Exception as e:
        return {
            "name": business["name"],
            "detail_url": full_url,
            "website": "",
            "phone": "",
            "email": "",
            "address": business.get("address_hint", ""),
            "city": "",
            "zip_code": "",
            "error": str(e),
        }


def _normalize_to_lead_format(detail: dict, search_query: str) -> dict:
    """Convert a scraped local.ch detail dict to the pipeline lead schema."""
    addr_parts = parse_address(detail.get("address", ""))

    return {
        "lead_id": generate_lead_id(detail["name"], detail.get("address", "")),
        "scraped_at": datetime.now().isoformat(),
        "search_query": search_query,
        "business_name": detail["name"],
        "category": "",  # Not easily available from list view
        "address": detail.get("address", ""),
        "city": detail.get("city", "") or addr_parts.get("city", ""),
        "state": addr_parts.get("state", ""),
        "zip_code": detail.get("zip_code", "") or addr_parts.get("zip_code", ""),
        "phone": detail.get("phone", ""),
        "google_maps_url": "",
        "rating": "",
        "review_count": "",
        "owner_name": "",
        "owner_email": detail.get("email", ""),
        "owner_phone": "",
        "emails": detail.get("email", ""),
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "status": "new",
        "website_url": "",
        "email_sent_date": "",
        "response_date": "",
        "notes": f"local.ch: {detail.get('detail_url', '')}",
        # Extra metadata for filtering
        "_source": "local.ch",
        "_filter_reason": "no_website_on_local_ch",
    }


def scrape_local_ch(
    search_url: str = None,
    query: str = None,
    city: str = None,
    language: str = "de",
    max_results: int = 50,
    max_workers: int = 8,
) -> list[dict]:
    """
    Scrape local.ch and return businesses WITHOUT websites as lead dicts.

    Args:
        search_url: Direct local.ch URL (takes priority over query+city).
        query: Search term (e.g., "maler").
        city: City name (e.g., "zuerich").
        language: de, fr, or it.
        max_results: Max businesses to return.
        max_workers: Parallel workers for detail page scraping.

    Returns:
        List of lead dicts (no-website businesses only).
    """
    httpx = _get_http_client()

    if search_url:
        base_url = search_url
        # Extract query/city from URL for search_query field
        m = re.search(r"/q/([^/]+)/([^/?]+)", search_url)
        search_query = f"{m.group(2)} in {m.group(1)}" if m else search_url
    else:
        if not query or not city:
            raise ValueError("Provide either --search-url or both --query and --city")
        base_url = _build_search_url(query, city, language)
        search_query = f"{query} in {city}"

    print(f"  Scraping: {base_url}")

    # Collect businesses from multiple pages
    all_businesses = []
    page = 1
    max_pages = max(1, (max_results * 3) // 40 + 1)  # 40 per page, ~50% need detail pages

    with httpx.Client(follow_redirects=True, timeout=15) as client:
        while len(all_businesses) < max_results * 3 and page <= max_pages:
            if page == 1:
                url = base_url
            else:
                url = base_url + (f"?page={page}" if "?" not in base_url else f"&page={page}")

            print(f"  Page {page}: {url}")
            businesses = _scrape_listing_page(url, client)

            if not businesses:
                break

            all_businesses.extend(businesses)
            print(f"  Page {page}: found {len(businesses)} listings (total: {len(all_businesses)})")

            if len(businesses) < 15:
                break  # Last page or very few results

            page += 1
            time.sleep(0.5)  # Be polite

        print(f"\n  Checking {len(all_businesses)} businesses for websites...")

        # Scrape detail pages in parallel
        no_website = []
        has_website = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_biz = {
                executor.submit(_scrape_detail_page, biz, client): biz
                for biz in all_businesses
            }

            for future in as_completed(future_to_biz):
                biz = future_to_biz[future]
                detail = future.result()
                if not detail:
                    continue

                if detail.get("website"):
                    has_website.append(detail)
                    if len(no_website) + len(has_website) <= 20:
                        print(f"    ✗ {detail['name']} — has website: {detail['website'][:50]}")
                else:
                    lead = _normalize_to_lead_format(detail, search_query)
                    no_website.append(lead)
                    if len(no_website) + len(has_website) <= 20:
                        print(f"    ✓ {detail['name']} — no website")

                    if len(no_website) >= max_results:
                        # Cancel remaining futures
                        for f in future_to_biz:
                            f.cancel()
                        break

    print(f"\n  Results: {len(no_website)} no website, {len(has_website)} has website")
    return no_website[:max_results]


def run_local_ch_pipeline(
    search_url: str = None,
    query: str = None,
    city: str = None,
    language: str = "de",
    max_results: int = 50,
    max_workers: int = 8,
) -> dict:
    """Run the full local.ch pipeline: scrape → filter → save."""
    if search_url:
        m = re.search(r"/q/([^/]+)/([^/?]+)", search_url)
        display = f"{m.group(2)} in {m.group(1)}" if m else search_url
    else:
        display = f"{query} in {city}"

    results = {
        "source": "local.ch",
        "search": display,
        "started_at": datetime.now().isoformat(),
        "no_website_count": 0,
        "output_file": None,
        "errors": [],
    }

    print(f"\n{'='*60}")
    print(f"SCRAPING local.ch: {display}")
    print(f"{'='*60}")

    try:
        leads = scrape_local_ch(
            search_url=search_url,
            query=query,
            city=city,
            language=language,
            max_results=max_results,
            max_workers=max_workers,
        )
    except Exception as e:
        results["errors"].append(str(e))
        print(f"ERROR: {e}")
        return results

    if not leads:
        results["errors"].append("No no-website businesses found")
        print("No results found.")
        return results

    results["no_website_count"] = len(leads)
    output_file = save_intermediate(leads, "local_ch_no_website")
    results["output_file"] = output_file
    results["completed_at"] = datetime.now().isoformat()

    print(f"\n{'='*60}")
    print("LOCAL.CH SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"No-website businesses: {results['no_website_count']}")
    print(f"Output file:           {results['output_file']}")
    print(f"\nNext: Claude Code will use WebSearch to enrich contacts, then save to Google Sheets.")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scrape local.ch for businesses without websites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query + city
  python3 scrape_local_ch.py --query "maler" --city "zuerich" --limit 20

  # Direct URL
  python3 scrape_local_ch.py --search-url "https://www.local.ch/de/q/zuerich/maler" --limit 20

  # French-speaking Switzerland
  python3 scrape_local_ch.py --query "peintre" --city "lausanne" --language fr --limit 20
        """,
    )

    parser.add_argument("--search-url", help="Direct local.ch search URL")
    parser.add_argument("--query", help="Search query (e.g., 'maler')")
    parser.add_argument("--city", help="City (e.g., 'zuerich')")
    parser.add_argument("--language", default="de", help="Language: de, fr, it")
    parser.add_argument("--limit", type=int, default=20, help="Max no-website results (default: 20)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers (default: 8)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.search_url and not (args.query and args.city):
        parser.error("Provide either --search-url OR both --query and --city")

    results = run_local_ch_pipeline(
        search_url=args.search_url,
        query=args.query,
        city=args.city,
        language=args.language,
        max_results=args.limit,
        max_workers=args.workers,
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if results["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
