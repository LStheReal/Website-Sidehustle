#!/usr/bin/env python3
"""
Google Sheets sync for the no-website leads pipeline.

Creates or appends to a Google Sheet with:
- 34-column schema (business info, contacts, pipeline status, pipeline tracking)
- Color-coded header sections (blue=business, green=contacts, yellow=status)
- Dropdown data validation on 'status' column
- Deduplication via lead_id

Usage:
    python3 update_sheet.py --input .tmp/leads.json
    python3 update_sheet.py --input .tmp/leads.json --sheet-url "https://docs.google.com/spreadsheets/d/..."
    python3 update_sheet.py --input .tmp/leads.json --sheet-name "Maler Zürich Leads"
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv

import gspread

# Add project root to path for shared utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
from execution.google_auth import get_credentials

load_dotenv()

# Default sheet name (used only when creating a brand new sheet)
DEFAULT_SHEET_NAME = "Website Builder — Leads"

# Canonical sheet URL — set in .env as LEADS_SHEET_URL
# When set, all skills append to this single sheet automatically.
CANONICAL_SHEET_URL = os.getenv("LEADS_SHEET_URL", "")

# Lead schema — columns for the Google Sheet (42 columns)
# MUST match COL in server.py and COLUMN_NAMES in _worker.js
LEAD_COLUMNS = [
    # Metadata (cols 1-3)
    "lead_id",
    "scraped_at",
    "search_query",
    # Business Info from Google Maps (cols 4-13)
    "business_name",
    "category",
    "address",
    "city",
    "state",
    "zip_code",
    "phone",
    "google_maps_url",
    "rating",
    "review_count",
    # Contact Info from enrichment (cols 14-20)
    "owner_name",
    "owner_email",
    "owner_phone",
    "emails",
    "facebook",
    "instagram",
    "linkedin",
    # Pipeline Status (cols 21-34)
    "status",
    "domain_option_1",
    "domain_option_1_purchase",
    "domain_option_1_price",
    "domain_option_2",
    "domain_option_2_purchase",
    "domain_option_2_price",
    "domain_option_3",
    "domain_option_3_purchase",
    "domain_option_3_price",
    "website_url",
    "email_sent_date",
    "response_date",
    "notes",
    # Pipeline Tracking (cols 35-42)
    "draft_url_1",
    "draft_url_2",
    "draft_url_3",
    "draft_url_4",
    "chosen_template",
    "next_action",
    "next_action_date",
    "acquisition_source",
]

# Column ranges for color coding (1-indexed)
METADATA_COLS = (1, 3)       # A-C: light grey
BUSINESS_COLS = (4, 13)      # D-M: light blue
CONTACT_COLS = (14, 20)      # N-T: light green
STATUS_COLS = (21, 34)       # U-AH: light yellow
TRACKING_COLS = (35, 42)     # AI-AP: light purple

# Status dropdown values
STATUS_VALUES = [
    "new",
    "website_creating",
    "website_created",
    "email_sent",
    "responded",
    "sold",
    "rejected",
]


def _col_letter(n: int) -> str:
    """Convert 1-based column number to Excel-style letter (1=A, 27=AA, etc.)."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_or_create_sheet(sheet_url: str = None, sheet_name: str = None) -> tuple:
    """
    Get existing sheet or create a new one with formatted headers.

    Args:
        sheet_url: Existing Google Sheet URL (appends to it).
        sheet_name: Name for new sheet (creates if no sheet_url).

    Returns:
        Tuple of (spreadsheet, worksheet, is_new).
    """
    creds = get_credentials()
    client = gspread.authorize(creds)

    if sheet_url:
        # Open existing sheet by URL
        if "/d/" in sheet_url:
            sheet_id = sheet_url.split("/d/")[1].split("/")[0]
        else:
            sheet_id = sheet_url

        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        is_new = False
        print(f"Opened existing sheet: {spreadsheet.title}")
    else:
        # Create new sheet
        name = sheet_name or DEFAULT_SHEET_NAME
        spreadsheet = client.create(name)
        worksheet = spreadsheet.sheet1

        # Set up headers
        worksheet.update(values=[LEAD_COLUMNS], range_name="A1")

        # Format header row
        end_col = _col_letter(len(LEAD_COLUMNS))

        # Bold + freeze header
        worksheet.format(f"A1:{end_col}1", {
            "textFormat": {"bold": True, "fontSize": 10},
        })
        worksheet.freeze(rows=1)

        # Color-code header sections
        _format_range(worksheet, METADATA_COLS, {"red": 0.90, "green": 0.90, "blue": 0.90})
        _format_range(worksheet, BUSINESS_COLS, {"red": 0.85, "green": 0.92, "blue": 1.0})
        _format_range(worksheet, CONTACT_COLS, {"red": 0.85, "green": 1.0, "blue": 0.85})
        _format_range(worksheet, STATUS_COLS, {"red": 1.0, "green": 0.97, "blue": 0.80})
        _format_range(worksheet, TRACKING_COLS, {"red": 0.93, "green": 0.87, "blue": 1.0})

        # Set column widths for readability
        _set_column_widths(worksheet)

        # Share with user email if configured
        user_email = os.getenv("USER_EMAIL")
        if user_email:
            try:
                spreadsheet.share(user_email, perm_type="user", role="writer")
                print(f"Shared sheet with {user_email}")
            except Exception as e:
                print(f"Warning: Could not share sheet: {e}")

        is_new = True
        print(f"Created new sheet: {name}")
        print(f"Sheet URL: {spreadsheet.url}")

    return spreadsheet, worksheet, is_new


def _format_range(worksheet, col_range: tuple, bg_color: dict):
    """Apply background color to a header column range."""
    start_col = _col_letter(col_range[0])
    end_col = _col_letter(col_range[1])
    try:
        worksheet.format(f"{start_col}1:{end_col}1", {
            "backgroundColor": bg_color,
        })
    except Exception:
        pass  # Non-critical formatting


def _set_column_widths(worksheet):
    """Set reasonable column widths for key columns."""
    try:
        # Use batch update for column widths
        requests = []
        width_map = {
            0: 110,   # lead_id
            1: 140,   # scraped_at
            2: 160,   # search_query
            3: 200,   # business_name
            4: 140,   # category
            5: 250,   # address
            6: 120,   # city
            9: 120,   # phone
            10: 200,  # google_maps_url
            13: 150,  # owner_name
            14: 200,  # owner_email
            20: 100,  # status
            21: 200,  # domain_option_1
            24: 200,  # domain_option_2
            27: 200,  # domain_option_3
            30: 200,  # website_url
            34: 250,  # draft_url_1
            35: 250,  # draft_url_2
            36: 250,  # draft_url_3
            37: 250,  # draft_url_4
            38: 120,  # chosen_template
            39: 200,  # next_action
            40: 130,  # next_action_date
            41: 120,  # acquisition_source
        }

        for col_idx, width in width_map.items():
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": worksheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": col_idx,
                        "endIndex": col_idx + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })

        if requests:
            worksheet.spreadsheet.batch_update({"requests": requests})
    except Exception:
        pass  # Non-critical formatting


def get_existing_lead_ids(worksheet) -> set:
    """Get all existing lead IDs from the sheet to avoid duplicates."""
    try:
        lead_ids = worksheet.col_values(1)
        return set(lead_ids[1:])  # Skip header
    except Exception:
        return set()


def append_leads_to_sheet(worksheet, leads: list[dict], existing_ids: set) -> int:
    """
    Append new leads to the sheet, skipping duplicates.

    Args:
        worksheet: gspread Worksheet object.
        leads: List of lead dicts matching LEAD_COLUMNS schema.
        existing_ids: Set of existing lead_id values.

    Returns:
        Number of leads actually added.
    """
    # Filter out duplicates
    new_leads = [lead for lead in leads if lead.get("lead_id") not in existing_ids]

    if not new_leads:
        print("No new leads to add (all duplicates)")
        return 0

    # Convert to rows
    rows = []
    for lead in new_leads:
        row = [str(lead.get(col, "")) for col in LEAD_COLUMNS]
        rows.append(row)

    # Batch append
    worksheet.append_rows(rows, value_input_option="RAW")

    print(f"Added {len(new_leads)} new leads to sheet")
    return len(new_leads)


def main():
    parser = argparse.ArgumentParser(description="Upload leads to Google Sheet")
    parser.add_argument("--input", required=True, help="Input JSON file with lead records")
    parser.add_argument("--sheet-url", help="Google Sheet URL to append to (default: LEADS_SHEET_URL from .env)")
    parser.add_argument("--sheet-name", help="Name for new sheet (only used when creating fresh, no existing URL)")

    args = parser.parse_args()

    # Use canonical URL from .env if no explicit --sheet-url given
    if not args.sheet_url and CANONICAL_SHEET_URL:
        args.sheet_url = CANONICAL_SHEET_URL
        print(f"Using canonical sheet from .env: {CANONICAL_SHEET_URL}")

    # Load leads
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            leads = json.load(f)
    except Exception as e:
        print(f"Error loading {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(leads)} leads from {args.input}")

    # Get or create sheet
    try:
        spreadsheet, worksheet, is_new = get_or_create_sheet(
            sheet_url=args.sheet_url,
            sheet_name=args.sheet_name,
        )
    except Exception as e:
        print(f"Error with Google Sheets: {e}", file=sys.stderr)
        sys.exit(1)

    # Get existing IDs for deduplication
    existing_ids = get_existing_lead_ids(worksheet)
    print(f"Found {len(existing_ids)} existing leads in sheet")

    # Append new leads
    added = append_leads_to_sheet(worksheet, leads, existing_ids)

    print(f"\nSheet URL: {spreadsheet.url}")
    print(f"Total leads added: {added}")

    return spreadsheet.url


if __name__ == "__main__":
    main()
