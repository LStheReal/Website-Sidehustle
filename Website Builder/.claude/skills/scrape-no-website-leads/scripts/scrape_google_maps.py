#!/usr/bin/env python3
"""
Scrape Google Maps business listings using Apify's compass/crawler-google-places actor.

Returns raw business data including the 'website' field which is used downstream
by filter_no_website.py to identify businesses without real websites.

Usage:
    python3 scrape_google_maps.py --search "Maler in Dietikon" --limit 10
    python3 scrape_google_maps.py --search "Elektriker in Zürich" --limit 50 --output .tmp/raw.json
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from apify_client import ApifyClient

# Make `execution.*` importable regardless of CWD.
_ROOT = Path(__file__).resolve().parents[4]  # .../Website Builder
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from execution.retry_utils import retry_with_backoff  # noqa: E402

load_dotenv()

ACTOR_ID = "compass/crawler-google-places"


@retry_with_backoff(max_attempts=3, initial_delay=5.0, backoff=2.0)
def _apify_call_with_retry(client, run_input: dict):
    """Run the Apify actor with retry on transient failures."""
    return client.actor(ACTOR_ID).call(run_input=run_input)


def scrape_google_maps(
    search_query: str,
    max_results: int = 10,
    location: str = None,
    language: str = "en",
) -> list[dict]:
    """
    Run the Apify Google Maps scraper actor.

    Args:
        search_query: Search term (e.g., "Maler in Dietikon" or "plumbers in Austin TX")
        max_results: Maximum number of places to scrape
        location: Optional location to focus the search
        language: Language code (default: en)

    Returns:
        List of business dictionaries with scraped data.
        Key fields: title, address, phone, website, categoryName, url, placeId,
                    totalScore, reviewsCount, city, state, postalCode, countryCode
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("Error: APIFY_API_TOKEN not found in .env", file=sys.stderr)
        return []

    client = ApifyClient(api_token)

    # Build search string with location if provided
    full_search = search_query
    if location and location.lower() not in search_query.lower():
        full_search = f"{search_query} in {location}"

    run_input = {
        "searchStringsArray": [full_search],
        "maxCrawledPlacesPerSearch": max_results,
        "language": language,
        "deeperCityScrape": False,
        "oneReviewPerRow": False,
    }

    print(f"Starting Google Maps scrape: '{full_search}' (limit: {max_results})...")

    try:
        run = _apify_call_with_retry(client, run_input)
    except Exception as e:
        print(f"Error running Apify actor (after retries): {e}", file=sys.stderr)
        return []

    if not run:
        print("Error: Actor run failed to start", file=sys.stderr)
        return []

    print(f"Scrape finished. Fetching results from dataset {run['defaultDatasetId']}...")

    results = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append(item)

    print(f"Retrieved {len(results)} businesses from Google Maps")
    return results


def save_results(results: list[dict], output: str = None, prefix: str = "gmaps") -> str:
    """Save results to a JSON file."""
    if not results:
        print("No results to save.")
        return None

    if output:
        filename = output
        output_dir = os.path.dirname(filename)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ".tmp"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/{prefix}_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Results saved to {filename}")
    return filename


def main():
    parser = argparse.ArgumentParser(description="Scrape Google Maps businesses using Apify")
    parser.add_argument("--search", required=True, help="Search query (e.g., 'Maler in Dietikon')")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results (default: 10)")
    parser.add_argument("--location", help="Optional location to focus search")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--output", default=None, help="Output file path (default: auto-generated in .tmp/)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON to stdout")

    args = parser.parse_args()

    results = scrape_google_maps(
        search_query=args.search,
        max_results=args.limit,
        location=args.location,
        language=args.language,
    )

    if not results:
        print("No results found or error occurred.")
        sys.exit(1)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        filename = save_results(results, output=args.output)
        if filename:
            print(f"\nSample result:")
            sample = results[0]
            for key in ["title", "address", "phone", "website", "categoryName"]:
                if key in sample:
                    print(f"  {key}: {sample.get(key)}")


if __name__ == "__main__":
    main()
