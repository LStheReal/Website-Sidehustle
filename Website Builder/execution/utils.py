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
