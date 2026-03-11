#!/usr/bin/env python3
"""
Find available domain names for a business.

Generates smart domain candidates from business name/type/city,
checks availability via RDAP (.ch) and WHOIS (.com),
returns 3 available suggestions with all business data bundled.
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx
import gspread
from dotenv import load_dotenv

# Add project root to path for shared utils
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate
from execution.google_auth import get_credentials

load_dotenv()


# --- Umlaut & ASCII conversion ---

UMLAUT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
}


def to_ascii_domain(text: str) -> str:
    """Convert text to ASCII-safe domain name part."""
    # Handle German umlauts first
    for umlaut, replacement in UMLAUT_MAP.items():
        text = text.replace(umlaut, replacement)
    # Decompose remaining unicode and strip accents
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Lowercase
    text = text.lower()
    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)
    # Remove anything that's not alphanumeric or hyphen
    text = re.sub(r"[^a-z0-9-]", "", text)
    # Collapse multiple hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    return text


# --- Domain candidate generation ---

def generate_candidates(name: str, business_type: str, city: str | None = None) -> list[str]:
    """Generate ~15-20 domain candidates from business info."""
    name_slug = to_ascii_domain(name)
    type_slug = to_ascii_domain(business_type)
    city_slug = to_ascii_domain(city) if city else None

    # Split name into words for variations
    name_words = name_slug.split("-")

    candidates = []

    def add(domain_part: str, tld: str):
        d = f"{domain_part}.{tld}"
        if d not in candidates and len(domain_part) >= 3:
            candidates.append(d)

    # --- .ch candidates (highest priority) ---
    tld = "ch"

    # Full name concatenated: swisstextilreinigung.ch
    add("".join(name_words), tld)

    # Full name hyphenated: swiss-textilreinigung.ch
    add(name_slug, tld)

    if city_slug:
        # Name + city concatenated: swisstextilreinigungdietikon.ch
        add("".join(name_words) + city_slug, tld)

        # Name + city hyphenated: swiss-textilreinigung-dietikon.ch
        add(f"{name_slug}-{city_slug}", tld)

        # Type + city: textilreinigung-dietikon.ch
        add(f"{type_slug}-{city_slug}", tld)

        # Type + city concatenated: textilreinigungdietikon.ch
        add(f"{type_slug}{city_slug}", tld)

        # Name concatenated + city: swisstextilreinigung-dietikon.ch
        add(f"{''.join(name_words)}-{city_slug}", tld)

    # Type only (if different from name): textilreinigung.ch
    if type_slug != name_slug:
        add(type_slug, tld)

    # If name has multiple words, try last word + city
    if len(name_words) > 1 and city_slug:
        add(f"{name_words[-1]}-{city_slug}", tld)
        add(f"{name_words[0]}-{name_words[-1]}-{city_slug}", tld)

    # --- .com candidates (second priority) ---
    tld = "com"

    add("".join(name_words), tld)
    add(name_slug, tld)

    if city_slug:
        add(f"{name_slug}-{city_slug}", tld)
        add(f"{''.join(name_words)}-{city_slug}", tld)
        add(f"{type_slug}-{city_slug}", tld)

    return candidates


# --- Availability checking ---

PRICE_ESTIMATES = {
    "ch": "~10-15 CHF/year",
    "com": "~10-15 USD/year",
}

# Registrar buy link (Porkbun — supports .ch and .com, direct search URL)
BUY_URL_TEMPLATE = "https://porkbun.com/checkout/search?q={domain}"


def get_buy_url(domain: str) -> str:
    """Generate a direct purchase/search URL for the domain."""
    return BUY_URL_TEMPLATE.format(domain=domain)


def check_rdap_ch(domain: str) -> dict:
    """Check .ch domain availability via RDAP (nic.ch)."""
    name = domain.rsplit(".", 1)[0]
    url = f"https://rdap.nic.ch/domain/{domain}"
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code == 404:
            return {"domain": domain, "available": True, "check_method": "rdap"}
        elif resp.status_code == 200:
            return {"domain": domain, "available": False, "check_method": "rdap"}
        else:
            # Unexpected status, fall back to DNS
            return check_dns(domain)
    except httpx.HTTPError:
        return check_dns(domain)


def check_whois(domain: str) -> dict:
    """Check domain availability via python-whois."""
    try:
        import whois
        w = whois.whois(domain)
        # If domain_name is None or empty, domain is likely available
        if w.domain_name is None:
            return {"domain": domain, "available": True, "check_method": "whois"}
        else:
            return {"domain": domain, "available": False, "check_method": "whois"}
    except Exception:
        # whois lookup failed — fall back to DNS
        return check_dns(domain)


def check_dns(domain: str) -> dict:
    """Fallback: check if domain resolves via DNS."""
    try:
        socket.getaddrinfo(domain, None)
        return {"domain": domain, "available": False, "check_method": "dns"}
    except socket.gaierror:
        return {"domain": domain, "available": True, "check_method": "dns"}


def check_availability(domain: str) -> dict:
    """Check domain availability using the best method for the TLD."""
    tld = domain.rsplit(".", 1)[-1]

    if tld == "ch":
        result = check_rdap_ch(domain)
    elif tld == "com":
        result = check_whois(domain)
    else:
        result = check_dns(domain)

    result["tld"] = f".{tld}"
    result["price_estimate"] = PRICE_ESTIMATES.get(tld, "unknown")
    return result


# --- Main ---

def find_domains(business_name: str, business_type: str, city: str | None = None,
                 extra_data: dict | None = None) -> dict:
    """Generate candidates, check availability, return top 3."""
    print(f"\n=== Finding domains for: {business_name} ({business_type}) ===")
    if city:
        print(f"    City: {city}")

    # Generate candidates
    candidates = generate_candidates(business_name, business_type, city)
    print(f"\nGenerated {len(candidates)} candidates:")
    for c in candidates:
        print(f"  - {c}")

    # Check availability with rate limiting
    all_checked = []
    available = []

    for i, domain in enumerate(candidates):
        tld = domain.rsplit(".", 1)[-1]

        result = check_availability(domain)
        all_checked.append(result)

        status = "AVAILABLE" if result["available"] else "taken"
        print(f"  [{i+1}/{len(candidates)}] {domain} — {status} ({result['check_method']})")

        if result["available"]:
            result["buy_url"] = get_buy_url(domain)
            available.append(result)
            if len(available) >= 3:
                print(f"\nFound 3 available domains, stopping early.")
                break

        # Rate limiting
        if tld == "ch":
            time.sleep(0.5)
        else:
            time.sleep(1.0)

    # Build business data bundle
    business_data = {
        "name": business_name,
        "type": business_type,
    }
    if city:
        business_data["city"] = city
    if extra_data:
        business_data.update(extra_data)

    # Build output
    output = {
        "generated_at": datetime.now().isoformat(),
        "business": business_data,
        "suggestions": available[:3],
        "all_checked": all_checked,
        "candidates_generated": len(candidates),
        "candidates_checked": len(all_checked),
    }

    return output


# --- Google Sheets integration ---

# Column indices (1-based) matching LEAD_COLUMNS in update_sheet.py
COL_LEAD_ID = 1
COL_STATUS = 21
COL_DOMAIN_OPTION_1 = 22
COL_DOMAIN_OPTION_2 = 23
COL_DOMAIN_OPTION_3 = 24
# COL_WEBSITE_URL = 25  — left empty until domain is chosen


def update_sheet_with_domains(sheet_url: str, lead_id: str, result: dict) -> bool:
    """
    Find the lead row by lead_id and update it with domain suggestions.

    Updates:
    - domain_option_1/2/3 → the 3 available domain suggestions
    - status → "website_creating"
    - website_url stays empty (filled later when domain is chosen)
    """
    creds = get_credentials()
    client = gspread.authorize(creds)

    # Open sheet
    if "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        sheet_id = sheet_url
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    # Find the row with this lead_id
    lead_ids = worksheet.col_values(COL_LEAD_ID)
    row_idx = None
    for i, lid in enumerate(lead_ids):
        if lid == lead_id:
            row_idx = i + 1  # 1-based row number
            break

    if row_idx is None:
        print(f"Warning: lead_id '{lead_id}' not found in sheet. Skipping sheet update.")
        return False

    suggestions = result.get("suggestions", [])
    if not suggestions:
        print("No available domains to write to sheet.")
        return False

    # Build batch update: HYPERLINK formulas for domain options + status
    # Using USER_ENTERED so Google Sheets parses the =HYPERLINK() formulas
    from gspread.utils import rowcol_to_a1

    cells = []
    for i, col in enumerate([COL_DOMAIN_OPTION_1, COL_DOMAIN_OPTION_2, COL_DOMAIN_OPTION_3]):
        if i < len(suggestions):
            domain = suggestions[i]["domain"]
            buy_url = suggestions[i].get("buy_url", get_buy_url(domain))
            cell_ref = rowcol_to_a1(row_idx, col)
            formula = f'=HYPERLINK("{buy_url}", "{domain}")'
            cells.append({"range": cell_ref, "values": [[formula]]})

    # Status cell (plain text)
    status_ref = rowcol_to_a1(row_idx, COL_STATUS)
    cells.append({"range": status_ref, "values": [["website_creating"]]})

    worksheet.batch_update(cells, value_input_option="USER_ENTERED")

    print(f"\nUpdated Google Sheet row {row_idx}:")
    for i, s in enumerate(suggestions):
        print(f"  domain_option_{i+1} → {s['domain']} (clickable buy link)")
    print(f"  status → website_creating")
    print(f"  website_url → (empty, to be decided)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Find available domain names for a business")
    parser.add_argument("--business-name", required=True, help="Business name")
    parser.add_argument("--business-type", required=True, help="Business type/category")
    parser.add_argument("--city", help="City (optional, for location-based domains)")
    parser.add_argument("--extra-data", help="JSON string with additional business data to pass through")
    parser.add_argument("--sheet-url", help="Google Sheet URL to update with domain suggestions")
    parser.add_argument("--lead-id", help="Lead ID to update in the sheet (required if --sheet-url is set)")
    args = parser.parse_args()

    extra_data = None
    if args.extra_data:
        try:
            extra_data = json.loads(args.extra_data)
        except json.JSONDecodeError:
            print(f"Warning: --extra-data is not valid JSON, ignoring: {args.extra_data}")

    result = find_domains(
        business_name=args.business_name,
        business_type=args.business_type,
        city=args.city,
        extra_data=extra_data,
    )

    # Save to .tmp
    output_path = save_intermediate(result, "domain_suggestions")
    print(f"\nResults saved to: {output_path}")

    # Print summary
    print(f"\n=== Domain Suggestions ===")
    if result["suggestions"]:
        for i, s in enumerate(result["suggestions"], 1):
            print(f"  {i}. {s['domain']}  ({s['price_estimate']}, checked via {s['check_method']})")
    else:
        print("  No available domains found. Try different name variations.")

    # Update Google Sheet if requested
    if args.sheet_url:
        lead_id = args.lead_id or (extra_data or {}).get("lead_id")
        if not lead_id:
            print("\nWarning: --sheet-url provided but no --lead-id or lead_id in --extra-data. Skipping sheet update.")
        else:
            update_sheet_with_domains(args.sheet_url, lead_id, result)

    # Also print JSON to stdout for piping
    print(f"\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
