#!/usr/bin/env python3
"""
Shared utility functions for the Website Builder pipeline.

Provides common helpers used across multiple skills:
- Lead ID generation (for deduplication)
- Value serialization (for Google Sheets)
- Address parsing
- Intermediate file saving
"""

import os
import re
import json
import hashlib
from urllib.parse import quote_plus
from datetime import datetime


def generate_lead_id(business_name: str, address: str) -> str:
    """
    Generate a unique 12-char ID for a lead based on name and address.
    Used for deduplication across scrape runs.

    Args:
        business_name: Name of the business.
        address: Full address string.

    Returns:
        12-character hex string (MD5 hash prefix).
    """
    unique_string = f"{business_name}|{address}".lower().strip()
    return hashlib.md5(unique_string.encode()).hexdigest()[:12]


def stringify_value(value) -> str:
    """
    Convert any value to a string suitable for Google Sheets.

    Handles: None, str, list, tuple, dict, and other types.

    Args:
        value: Any Python value.

    Returns:
        String representation safe for Google Sheets cells.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if v:
                parts.append(f"{k}: {v}")
        return "; ".join(parts) if parts else ""
    return str(value)


def clean_address(address: str, business_name: str = "") -> str:
    """
    Clean scraped address text and strip rating/status noise.

    This is mainly used for local.ch/Maps snippets where the address cell can
    accidentally include review text or business-name fragments before the
    actual street address.
    """
    if not address:
        return ""

    text = re.sub(r"\s+", " ", str(address)).strip(" |,-")
    text = re.sub(r"(\d{4,5})([A-ZÄÖÜ])", r"\1 \2", text)
    text = re.sub(r"([a-zà-ÿß])([A-ZÄÖÜ][a-zà-ÿ])", r"\1 \2", text)

    street_types = (
        "strasse", "straße", "gasse", "gässli", "gaessli", "weg", "allee", "platz", "quai", "ring",
        "pfad", "steig", "stieg", "ufer", "rain", "park", "avenue", "route",
        "via", "viale", "chemin", "ruelle", "rue", "boulevard", "impasse",
    )
    street_type_pattern = "|".join(street_types)
    street_name_core_pattern = (
        rf"(?:"
        rf"[A-ZÄÖÜ][A-Za-zÀ-ÿ.'/-]*(?:{street_type_pattern})"
        rf"|"
        rf"[A-ZÄÖÜ][A-Za-zÀ-ÿ.'/-]*(?:\s+[A-ZÄÖÜ][A-Za-zÀ-ÿ.'/-]*)*\s+"
        rf"(?:{street_type_pattern})"
        rf")"
    )
    street_name_pattern = rf"(?<![A-Za-zÀ-ÿ0-9'’/-]){street_name_core_pattern}"

    # Remove common rating/status phrases that sometimes get prepended.
    noise_patterns = [
        r"^Bewertung\s+[\d.,]+\s+von\s+5\s+Sternen(?:\s+bei\s+\d+\s+Bewertungen?)?",
        r"^Bewertung\s+[\d.,]+\s+von\s+5\s+Sternen(?:\s+bei\s+\d+)?",
        r"^\d+(?:[.,]\d+)?/5(?:\s*\(\d+\))?",
        r"^Noch\s+keine\s+Bewertungen",
        r"^(?:Geöffnet|Geschlossen|Offen)(?:\s+bis\s+\d{1,2}:\d{2})?",
        r"^(?:Temporär\s+geschlossen|Vorübergehend\s+geschlossen)",
        r"^[A-Z0-9&+.' -]{8,}(?="
        + street_name_pattern
        + r")",
    ]
    for pattern in noise_patterns:
        while True:
            cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" |,-")
            if cleaned == text:
                break
            text = cleaned

    business_name = re.sub(r"\s+", " ", str(business_name or "")).strip(" |,-")
    if business_name:
        business_variants = [business_name, re.sub(r"\s+", "", business_name)]
        parts = business_name.split()
        for size in range(1, min(3, len(parts)) + 1):
            suffix = " ".join(parts[-size:])
            business_variants.extend([suffix, re.sub(r"\s+", "", suffix)])

        for variant in business_variants:
            if not variant:
                continue
            text = re.sub(
                rf"^{re.escape(variant)}",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            ).strip(" |,-")

    # local.ch snippets sometimes glue the business name to the street name.
    text = re.sub(
        rf"([a-zà-ÿß])({street_name_core_pattern})",
        r"\1 \2",
        text,
    )
    text = re.sub(
        rf"([A-Z]{{2,}})({street_name_core_pattern})",
        r"\1 \2",
        text,
    )
    text = re.sub(
        rf"(['’][A-Z]{{1,6}})({street_name_core_pattern})",
        r"\1 \2",
        text,
    )
    text = re.sub(
        rf"\b([A-Z])({street_name_core_pattern})",
        r"\1 \2",
        text,
    )

    # If the snippet contains extra text before the actual street, keep only
    # the first plausible street address onward.
    inline_address_pattern = re.compile(
        rf"("
        rf"{street_name_pattern}\s*\d+[A-Za-z]?"
        rf"(?:,\s*|\s+)\d{{4,5}}\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'/()\\-]*)",
    )
    inline_matches = list(inline_address_pattern.finditer(text))
    if inline_matches:
        text = min(
            inline_matches,
            key=lambda match: (match.group(1).count(" "), len(match.group(1))),
        ).group(1).strip(" |,-")
    else:
        street_number_pattern = re.compile(
            rf"({street_name_pattern}\s*\d+[A-Za-z]?)"
        )
        street_number_matches = list(street_number_pattern.finditer(text))
        if street_number_matches:
            text = min(
                street_number_matches,
                key=lambda match: (match.group(1).count(" "), len(match.group(1))),
            ).group(1).strip(" |,-")

    address_pattern = re.compile(
        rf"(?:^|[\s,;|])("
        rf"{street_name_pattern}\s*\d+[A-Za-z]?"
        rf"(?:,\s*|\s+)\d{{4,5}}\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'/()\\-]*)",
    )
    matches = list(address_pattern.finditer(text))
    if matches:
        text = matches[-1].group(1).strip(" |,-")

    return re.sub(r"\s+", " ", text).strip(" |,-")


def parse_address(address: str) -> dict:
    """
    Parse an address string into components.
    Handles common Swiss/European and US formats.

    Args:
        address: Full address string from Google Maps.

    Returns:
        Dict with keys: city, state, zip_code, country.
    """
    parts = {
        "city": "",
        "state": "",
        "zip_code": "",
        "country": "",
    }

    if not address:
        return parts

    # Try to extract Swiss/European postal code (4-5 digits at start or after comma)
    ch_zip_match = re.search(r'\b(\d{4,5})\s+(\w[\w\s-]*?)(?:,|$)', address)
    if ch_zip_match:
        parts["zip_code"] = ch_zip_match.group(1)
        parts["city"] = ch_zip_match.group(2).strip()

    # Try US zip code (5 digits, optionally with -XXXX extension)
    if not parts["zip_code"]:
        us_zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', address)
        if us_zip_match:
            parts["zip_code"] = us_zip_match.group(1)

    # Try to extract US state (2-letter code)
    state_match = re.search(r'\b([A-Z]{2})\b', address)
    if state_match:
        parts["state"] = state_match.group(1)

    # Try to extract city (part before state or zip in US format)
    if parts["state"] and not parts["city"]:
        city_match = re.search(rf',\s*([^,]+),?\s*{parts["state"]}', address)
        if city_match:
            parts["city"] = city_match.group(1).strip()

    # Try to detect country from address
    address_lower = address.lower()
    if "switzerland" in address_lower or "schweiz" in address_lower or "suisse" in address_lower:
        parts["country"] = "CH"
    elif "germany" in address_lower or "deutschland" in address_lower:
        parts["country"] = "DE"
    elif "austria" in address_lower or "österreich" in address_lower:
        parts["country"] = "AT"
    elif "france" in address_lower:
        parts["country"] = "FR"
    elif "italy" in address_lower or "italia" in address_lower:
        parts["country"] = "IT"

    return parts


def build_google_maps_url(
    business_name: str = "",
    address: str = "",
    place_id: str = "",
    existing_url: str = "",
) -> str:
    """
    Return the best available Google Maps URL for a business.

    Preference order:
    1. Existing Google Maps URL from scraper output
    2. Generated Google Maps search URL from business name + address
    3. Empty string if not enough data is available
    """
    existing_url = (existing_url or "").strip()
    if existing_url:
        return existing_url

    query_parts = [part.strip() for part in [business_name, address] if part and str(part).strip()]
    if not query_parts:
        return ""

    query = quote_plus(", ".join(query_parts))
    base_url = f"https://www.google.com/maps/search/?api=1&query={query}"

    place_id = (place_id or "").strip()
    if place_id:
        return f"{base_url}&query_place_id={quote_plus(place_id)}"

    return base_url


def save_intermediate(data, prefix: str, output_dir: str = ".tmp") -> str:
    """
    Save intermediate data to a timestamped JSON file.

    Args:
        data: Data to save (dict or list, must be JSON-serializable).
        prefix: Filename prefix (e.g., "gmaps_raw", "filtered", "enriched").
        output_dir: Directory to save in (default: .tmp/).

    Returns:
        Path to the saved file.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_dir, f"{prefix}_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved to {filename}")
    return filename
