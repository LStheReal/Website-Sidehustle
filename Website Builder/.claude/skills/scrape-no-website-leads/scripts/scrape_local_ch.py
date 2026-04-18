#!/usr/bin/env python3
"""
Scrape local.ch for businesses WITHOUT websites — Playwright-based scraper.

local.ch renders via JavaScript. This scraper uses Playwright (headless Chromium)
to wait for JS-rendered content before extracting business data.
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
import asyncio
import subprocess
from datetime import datetime
from urllib.parse import urljoin, quote

# Add project root for shared utils
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..", "..", "..", "..")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPT_DIR)

from execution.utils import save_intermediate, generate_lead_id, parse_address, stringify_value
from filter_no_website import _domain_matches_blocklist, _extract_domain

BASE_URL = "https://www.local.ch"

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
    # Swiss government / map services (appear as map embeds on detail pages)
    "swisstopo.admin.ch", "admin.ch",
    "map.geo.admin.ch",
    # Map tile providers (attribution links in embedded maps)
    "openstreetmap.org", "www.openstreetmap.org",
    # Cookie consent / tracking infrastructure (appear in page source, not business sites)
    "onetrust.com", "www.onetrust.com",
    "cookiebot.com", "usercentrics.eu",
    # Messaging apps (not websites)
    "wa.me",   # WhatsApp
    "t.me",    # Telegram
}


def _get_soup(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "-q"])
        from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


async def _ensure_playwright(playwright):
    """
    Launch Chromium browser. Auto-installs browsers if missing.
    Returns a Browser instance.
    """
    try:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        return browser
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e).lower():
            import subprocess
            print("  Installing Playwright browsers (one-time setup)...")
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      "--disable-blink-features=AutomationControlled"],
            )
            return browser
        raise


async def _get_page_html(page, url: str, timeout_ms: int = 15000) -> str:
    """Navigate to URL, wait for JS render, return page HTML."""
    try:
        # Use domcontentloaded (not networkidle) — local.ch keeps background requests alive
        # which causes networkidle to hang until the full timeout expires.
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # Give JS a short fixed time to inject dynamic content (listings, contact info)
        await asyncio.sleep(2)
    except Exception:
        # Timeout or navigation error — return whatever has rendered so far
        pass
    return await page.content()


def _build_search_url(query: str, city: str, language: str = "de", page: int = 1) -> str:
    """Build a local.ch search URL."""
    q = quote(query.lower().replace(" ", "-"))
    c = quote(city.lower().replace(" ", "-").replace("ü", "ue").replace("ä", "ae").replace("ö", "oe"))
    url = f"{BASE_URL}/{language}/q/{c}/{q}"
    if page > 1:
        url += f"?page={page}"
    return url


async def _scrape_listing_page_async(page, url: str) -> list[dict]:
    """
    Scrape one local.ch search results page using a Playwright page.
    Returns list of dicts with {name, detail_url, address_hint}.
    """
    try:
        html = await _get_page_html(page, url, timeout_ms=15000)
        soup = _get_soup(html)

        # Find all listing elements (desktop or mobile variants)
        items = soup.find_all(attrs={"data-testid": re.compile(r"^list-element-")})

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


async def _scrape_detail_page_async(semaphore, context, business: dict) -> dict | None:
    """
    Visit a local.ch detail page using a dedicated Playwright page.
    Each call opens and closes its own page (safe for concurrent use).
    Returns extracted business data dict, or a fallback dict on error.
    """
    async with semaphore:
        page = await context.new_page()
        try:
            detail_url = business["detail_url"]
            full_url = urljoin(BASE_URL, detail_url)

            try:
                await page.goto(full_url, wait_until="domcontentloaded", timeout=10000)
                # Wait for JS to inject contact details (data-testid elements appear after render)
                await page.wait_for_selector("[data-testid]", timeout=5000)
            except Exception:
                pass  # Continue with whatever rendered

            html = await page.content()
            soup = _get_soup(html)
            full_text = soup.get_text(" ", strip=True)

            # Extract website — external links that aren't directory/local.ch
            external_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    continue
                domain = _extract_domain(href)
                base_domain = domain.removeprefix("www.")
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

            # Extract address — prefer the <address> HTML element, fall back to regex
            address = business.get("address_hint", "")
            addr_el = soup.find("address")
            if addr_el:
                address = addr_el.get_text(" ", strip=True)
            else:
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
                "detail_url": urljoin(BASE_URL, business["detail_url"]),
                "website": "",
                "phone": "",
                "email": "",
                "address": business.get("address_hint", ""),
                "city": "",
                "zip_code": "",
                "error": str(e),
            }
        finally:
            await page.close()


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


async def _scrape_local_ch_async(
    base_url: str,
    search_query: str,
    max_results: int,
    max_workers: int,
) -> list[dict]:
    """Async orchestrator: launch browser, scrape listing pages, then detail pages in parallel."""
    from playwright.async_api import async_playwright

    # Suppress "Future exception was never retrieved" noise from Playwright's internal
    # timeout futures when we cancel tasks early (browser cleanup is always clean).
    loop = asyncio.get_running_loop()
    _orig_handler = loop.get_exception_handler()

    def _suppress_cleanup_noise(loop, ctx):
        if "future exception was never retrieved" in ctx.get("message", "").lower():
            return
        (_orig_handler or loop.default_exception_handler)(loop, ctx)

    loop.set_exception_handler(_suppress_cleanup_noise)

    async with async_playwright() as pw:
        browser = await _ensure_playwright(pw)
        try:
            context = await browser.new_context(
                locale="de-CH",
                extra_http_headers={"Accept-Language": "de-CH,de;q=0.9,en;q=0.8"},
                viewport={"width": 1280, "height": 900},
            )

            # Stage 1: sequential listing pages (reuse one page across pagination)
            listing_page = await context.new_page()
            all_businesses = []
            page_num = 1
            # ~20 results/page; need a buffer since many businesses will have websites.
            # For small limits (debug/test), keep it proportional. For production, cap at 150.
            max_businesses_to_check = min(150, max(60, max_results * 10))
            max_pages = min(20, max_businesses_to_check // 20 + 1)

            while len(all_businesses) < max_businesses_to_check and page_num <= max_pages:
                if page_num == 1:
                    url = base_url
                else:
                    url = base_url + (f"?page={page_num}" if "?" not in base_url else f"&page={page_num}")

                print(f"  Page {page_num}: {url}")
                businesses = await _scrape_listing_page_async(listing_page, url)

                if not businesses:
                    break

                all_businesses.extend(businesses)
                print(f"  Page {page_num}: found {len(businesses)} listings (total: {len(all_businesses)})")

                if len(businesses) < 15:
                    break  # Last page or very few results

                page_num += 1
                await asyncio.sleep(0.5)  # Be polite

            await listing_page.close()

            # Stage 2: concurrent detail pages (semaphore limits to max_workers)
            print(f"\n  Checking {len(all_businesses)} businesses for websites...")
            semaphore = asyncio.Semaphore(max_workers)
            # Wrap as real Tasks so we can cancel them on early exit.
            # The done callback silences "future exception was never retrieved" on aborted tasks.
            def _swallow(f):
                if not f.cancelled():
                    f.exception()

            tasks = []
            for biz in all_businesses:
                t = asyncio.ensure_future(_scrape_detail_page_async(semaphore, context, biz))
                t.add_done_callback(_swallow)
                tasks.append(t)

            no_website = []
            has_website = []

            # Early-exit: after checking this many businesses, abort if yield is too low
            EARLY_EXIT_SAMPLE = 20
            EARLY_EXIT_MIN_YIELD = 0.015  # 1.5%

            try:
                for coro in asyncio.as_completed(tasks):
                    detail = await coro
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
                            break

                    # Early exit: if we've checked enough and yield is far too low, stop wasting time
                    processed = len(no_website) + len(has_website)
                    if processed >= EARLY_EXIT_SAMPLE and len(no_website) / processed < EARLY_EXIT_MIN_YIELD:
                        print(f"  ⚡ Early exit: {len(no_website)}/{processed} checked, "
                              f"yield {len(no_website)/processed:.1%} < {EARLY_EXIT_MIN_YIELD:.0%} threshold — skipping combo")
                        break
            finally:
                # Cancel any tasks still waiting (early exit or error)
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            await browser.close()

    loop.set_exception_handler(_orig_handler)
    print(f"\n  Results: {len(no_website)} no website, {len(has_website)} has website")
    return no_website[:max_results]


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
    return asyncio.run(_scrape_local_ch_async(base_url, search_query, max_results, max_workers))


# Personal/owner email providers — used to prefer owner emails over generic business emails
_PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "bluewin.ch", "gmx.ch", "gmx.net", "outlook.com", "hotmail.com",
    "yahoo.com", "yahoo.de", "yahoo.fr", "icloud.com", "proton.me", "protonmail.com",
    "sunrise.ch", "hispeed.ch", "swissonline.ch",
}

# Social media patterns to extract from search snippets/URLs
_SOCIAL_RE = {
    "facebook": re.compile(r'https?://(?:www\.)?facebook\.com/([^\s/"?&#]+)'),
    "instagram": re.compile(r'https?://(?:www\.)?instagram\.com/([^\s/"?&#]+)'),
    "linkedin":  re.compile(r'https?://(?:www\.)?linkedin\.com/(?:in|company)/([^\s/"?&#]+)'),
}
_SOCIAL_SKIP = {"pages", "groups", "events", "sharer", "share", "login", "signup", "photo"}

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'\+41[\s\d]{9,}|\b0\d{2}[\s\d]{6,}')


def _enrich_leads_with_search(leads: list[dict]) -> list[dict]:
    """
    Enrich leads with DuckDuckGo contact search — deterministic, no LLM.

    local.ch already extracts phone + email from detail pages.
    This step adds: personal owner emails (gmail/bluewin/etc.),
    social media profiles (Facebook, Instagram, LinkedIn).

    Uses the same search logic as enrich_contacts.py but extracts
    structured data with regex instead of relying on a Claude agent.
    """
    from enrich_contacts import search_business_contacts

    print(f"\n  Enriching {len(leads)} leads via DuckDuckGo search...")

    for i, lead in enumerate(leads, 1):
        name = lead.get("business_name", "")
        city = lead.get("city", "")
        category = lead.get("category", "")
        print(f"  [{i}/{len(leads)}] {name}")

        try:
            search_data = search_business_contacts(name, category, city)
            # Combine all text from search results (titles + snippets + URLs)
            all_text = " ".join(
                " ".join([r.get("title", ""), r.get("snippet", ""), r.get("url", "")])
                for r in search_data.get("results", [])
            )

            # Emails — prefer personal (owner) emails over generic ones
            all_emails = [
                e for e in _EMAIL_RE.findall(all_text)
                if not any(skip in e for skip in ("local.ch", "duckduckgo", "example."))
            ]
            personal = [e for e in all_emails if e.split("@")[-1].lower() in _PERSONAL_EMAIL_DOMAINS]
            best_email = (personal or all_emails or [""])[0]

            if not lead.get("owner_email") and best_email:
                lead["owner_email"] = best_email
            if not lead.get("emails") and best_email:
                lead["emails"] = best_email

            # Phone — fill if local.ch didn't find one
            if not lead.get("phone"):
                phones = _PHONE_RE.findall(all_text)
                if phones:
                    lead["phone"] = phones[0].strip()

            # Social media
            for platform, pattern in _SOCIAL_RE.items():
                if not lead.get(platform):
                    m = pattern.search(all_text)
                    if m and m.group(1) not in _SOCIAL_SKIP:
                        lead[platform] = f"https://www.{platform}.com/{m.group(1)}"

        except Exception as e:
            print(f"    Warning: enrichment failed — {e}")

    return leads


def _save_to_sheets(leads: list[dict], no_auto_build: bool = False) -> bool:
    """
    Save leads to Google Sheets via update_sheet.py.
    Auto-builds 4 draft websites per lead unless no_auto_build=True.
    Mirrors the Google Maps pipeline behavior exactly.
    """
    update_script = os.path.join(SCRIPT_DIR, "update_sheet.py")
    if not os.path.exists(update_script):
        print(f"\n  Skipping Sheets sync: update_sheet.py not found at {update_script}")
        return False

    leads_file = save_intermediate(leads, "local_ch_final")

    cmd = [sys.executable, update_script, "--input", leads_file]
    if no_auto_build:
        cmd.append("--no-auto-build")

    print(f"\n  Saving {len(leads)} leads to Google Sheets...")
    try:
        result = subprocess.run(cmd, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"\n  Error saving to Sheets: {e}")
        return False


def run_local_ch_pipeline(
    search_url: str = None,
    query: str = None,
    city: str = None,
    language: str = "de",
    max_results: int = 50,
    max_workers: int = 8,
    enrich: bool = True,
    auto_build: bool = True,
) -> dict:
    """Run the full local.ch pipeline: scrape → enrich → save to Sheets → auto-build drafts."""
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

    # Step 2: Enrich contacts via DuckDuckGo (deterministic, no LLM)
    if enrich:
        leads = _enrich_leads_with_search(leads)

    # Save intermediate (raw scrape + enrichment)
    output_file = save_intermediate(leads, "local_ch_no_website")
    results["output_file"] = output_file
    results["completed_at"] = datetime.now().isoformat()

    print(f"\n{'='*60}")
    print("LOCAL.CH SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"No-website businesses: {results['no_website_count']}")
    print(f"Output file:           {results['output_file']}")

    # Record to search coverage tracker (non-fatal if it fails)
    try:
        from search_tracker import auto_record_local_ch
        # businesses_checked = total detail pages visited (no_website + has_website).
        # We only have the no_website count here; use it as a lower-bound estimate.
        # The async scraper visits up to max(150, limit*15) businesses — use that as checked count.
        businesses_checked_estimate = max(len(leads), max(150, max_results * 15))
        auto_record_local_ch(
            query=query or "",
            city=city or "",
            businesses_checked=businesses_checked_estimate,
            no_website_count=len(leads),
        )
    except Exception as _tracker_err:
        pass  # Tracker is non-critical

    # Step 3: Save to Google Sheets + auto-build draft websites
    _save_to_sheets(leads, no_auto_build=not auto_build)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scrape local.ch for businesses without websites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline (scrape → enrich → Sheets → auto-build drafts)
  python3 scrape_local_ch.py --query "maler" --city "aarau" --limit 10

  # Scrape only (skip enrichment + Sheets + draft building)
  python3 scrape_local_ch.py --query "maler" --city "aarau" --limit 10 --no-enrich --no-auto-build

  # Scrape + enrich but skip draft building
  python3 scrape_local_ch.py --query "maler" --city "aarau" --limit 10 --no-auto-build

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
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip DuckDuckGo contact enrichment")
    parser.add_argument("--no-auto-build", action="store_true",
                        help="Skip automatic draft website building (still saves to Sheets)")
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
        enrich=not args.no_enrich,
        auto_build=not args.no_auto_build,
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if results["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
