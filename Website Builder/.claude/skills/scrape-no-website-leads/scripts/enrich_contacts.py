#!/usr/bin/env python3
"""
Search for contact information about businesses without websites.

This script handles the DETERMINISTIC part only:
1. DuckDuckGo HTML search — multiple queries per business (free, no API key)
2. Parse and structure the raw search results
3. Save to JSON for Claude Code to extract contacts from

The INTELLIGENT extraction (reading search results → structured contacts)
is done by Claude Code itself when running the skill — no separate API key needed.

Rate limiting is built in to avoid DuckDuckGo blocks:
- 1.5s delay between search queries
- Exponential backoff on HTTP 429 (2→4→8→16s, max 3 retries)
- max_workers=3 (conservative parallelism)

Usage:
    python3 enrich_contacts.py --input .tmp/no_website.json --output .tmp/search_results.json
"""

import os
import sys
import json
import re
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

import httpx

# Rate limiting
SEARCH_DELAY = 1.5  # seconds between DuckDuckGo queries
MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0  # seconds


def _search_duckduckgo(query: str, max_retries: int = MAX_RETRIES) -> str:
    """
    Execute a single DuckDuckGo HTML search with retry logic.

    Args:
        query: Search query string.
        max_retries: Maximum retries on failure/rate-limit.

    Returns:
        Raw HTML response text, or empty string on failure.
    """
    search_url = f"https://html.duckduckgo.com/html/?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    backoff = INITIAL_BACKOFF

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(search_url, headers=headers)

                if response.status_code == 429:
                    if attempt < max_retries:
                        print(f"    Rate limited, waiting {backoff:.0f}s...")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    return ""

                response.raise_for_status()
                return response.text

        except Exception as e:
            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2
            else:
                print(f"    Search failed after {max_retries} retries: {e}")
                return ""

    return ""


def _parse_search_results(html: str) -> list[dict]:
    """
    Parse DuckDuckGo HTML search results into structured data.

    Returns list of dicts with 'title', 'url', 'snippet' keys.
    """
    results = []

    # Extract result snippets
    snippet_pattern = r'class="result__snippet"[^>]*>(.*?)<'
    snippets = re.findall(snippet_pattern, html, re.DOTALL)

    # Extract result titles and URLs
    title_pattern = r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)<'
    titles = re.findall(title_pattern, html, re.DOTALL)

    for i, (url, title) in enumerate(titles[:8]):
        # Clean up DuckDuckGo redirect URLs
        if "uddg=" in url:
            actual_url = re.search(r'uddg=([^&]+)', url)
            if actual_url:
                url = unquote(actual_url.group(1))

        result = {
            "title": re.sub(r'<[^>]+>', '', title).strip(),
            "url": url,
            "snippet": re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else "",
        }
        results.append(result)

    return results


def search_business_contacts(
    business_name: str,
    category: str = None,
    city: str = None,
    state: str = None,
) -> dict:
    """
    Search DuckDuckGo for owner/contact info about a business without a website.

    Runs multiple targeted search queries to cast a wide net:
    1. General contact search
    2. LinkedIn/professional search
    3. Social media search

    Args:
        business_name: Name of the business.
        category: Business category (e.g., "Painter", "Plumber").
        city: City name.
        state: State/canton/region.

    Returns:
        Dict with 'queries' (list of query strings) and 'results' (list of search results).
    """
    if not business_name:
        return {"queries": [], "results": []}

    location = " ".join(filter(None, [city, state]))

    # Build multiple search queries for broader coverage
    queries = [
        f'"{business_name}" owner email contact {location}',
        f'"{business_name}" {category or ""} {location} linkedin',
        f'"{business_name}" facebook OR instagram {location}',
    ]

    all_results = []

    for query in queries:
        query = query.strip()
        html = _search_duckduckgo(query)

        if html:
            results = _parse_search_results(html)
            for r in results:
                r["query"] = query
            all_results.extend(results)

        # Rate limit between queries
        time.sleep(SEARCH_DELAY)

    return {
        "queries": queries,
        "results": all_results,
    }


def search_single_business(business: dict) -> dict:
    """
    Search for contact info for a single business.

    Args:
        business: Dict from Google Maps scraper.

    Returns:
        Dict with 'gmaps' (original data) and 'search_data' (DuckDuckGo results).
    """
    name = business.get("title", "Unknown")
    category = business.get("categoryName", "")
    city = business.get("city", "")
    state = business.get("state", "")

    search_data = search_business_contacts(
        business_name=name,
        category=category,
        city=city,
        state=state,
    )

    return {
        "gmaps": business,
        "search_data": search_data,
    }


def search_businesses_batch(
    businesses: list[dict],
    max_workers: int = 3,
) -> list[dict]:
    """
    Search for contact info for multiple businesses in parallel.

    Args:
        businesses: List of no-website business dicts.
        max_workers: Parallel threads (keep low — DuckDuckGo rate limits).

    Returns:
        List of dicts, each with 'gmaps' and 'search_data' keys.
    """
    print(f"\nSearching for contact info for {len(businesses)} businesses...")
    print(f"  Workers: {max_workers} | Search delay: {SEARCH_DELAY}s per query")

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_business = {
            executor.submit(search_single_business, b): b
            for b in businesses
        }

        for i, future in enumerate(as_completed(future_to_business), 1):
            business = future_to_business[future]
            try:
                result = future.result()
                results.append(result)
                n_results = len(result.get("search_data", {}).get("results", []))
                print(f"  [{i}/{len(businesses)}] {business.get('title', '?')} — {n_results} search results")
            except Exception as e:
                print(f"  [{i}/{len(businesses)}] Error: {business.get('title', '?')} — {e}")
                results.append({
                    "gmaps": business,
                    "search_data": {"queries": [], "results": [], "error": str(e)},
                })

    # Summary
    total_results = sum(len(r.get("search_data", {}).get("results", [])) for r in results)
    with_results = sum(1 for r in results if r.get("search_data", {}).get("results"))
    print(f"\nSearch complete: {with_results}/{len(results)} businesses found search results ({total_results} total)")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Search DuckDuckGo for contact info about no-website businesses"
    )
    parser.add_argument("--input", required=True, help="Input JSON file (from filter_no_website.py)")
    parser.add_argument("--output", default=None, help="Output JSON file (default: auto in .tmp/)")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers (default: 3)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON to stdout")

    args = parser.parse_args()

    # Load businesses
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            businesses = json.load(f)
    except Exception as e:
        print(f"Error loading {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(businesses)} businesses from {args.input}")

    # Search
    results = search_businesses_batch(businesses, max_workers=args.workers)

    # Save
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if args.output:
            output_file = args.output
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
        else:
            os.makedirs(".tmp", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f".tmp/search_results_{timestamp}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\nSearch results saved to {output_file}")


if __name__ == "__main__":
    main()
