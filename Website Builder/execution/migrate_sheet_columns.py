#!/usr/bin/env python3
"""
One-time migration: fix the leads sheet column layout.

The old schema had 35 columns (missing domain purchase/price columns and acquisition_source).
The server/worker code expects 42 columns. This script:

1. Reads all data from the existing sheet
2. Maps old column positions to new column positions
3. Rewrites the header row with the correct 42-column schema
4. Rewrites all data rows with values shifted to the correct columns
5. Sets acquisition_source for existing leads (outreach if scraped, organic if registered_no_code)
6. Re-applies header formatting and color coding

Usage:
    cd "Website Builder"
    source .venv/bin/activate
    python3 execution/migrate_sheet_columns.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
import gspread

from execution.google_auth import get_credentials

load_dotenv()

# Old 35-column schema (what the sheet currently has)
OLD_COLUMNS = [
    "lead_id", "scraped_at", "search_query",
    "business_name", "category", "address", "city", "state", "zip_code",
    "phone", "google_maps_url", "rating", "review_count",
    "owner_name", "owner_email", "owner_phone", "emails",
    "facebook", "instagram", "linkedin",
    "status",
    "domain_option_1", "domain_option_2", "domain_option_3",
    "website_url", "email_sent_date", "response_date", "notes",
    "draft_url_1", "draft_url_2", "draft_url_3", "draft_url_4",
    "chosen_template", "next_action", "next_action_date",
]

# New 42-column schema (matches server.py COL and _worker.js COLUMN_NAMES)
NEW_COLUMNS = [
    "lead_id", "scraped_at", "search_query",
    "business_name", "category", "address", "city", "state", "zip_code",
    "phone", "google_maps_url", "rating", "review_count",
    "owner_name", "owner_email", "owner_phone", "emails",
    "facebook", "instagram", "linkedin",
    "status",
    "domain_option_1", "domain_option_1_purchase", "domain_option_1_price",
    "domain_option_2", "domain_option_2_purchase", "domain_option_2_price",
    "domain_option_3", "domain_option_3_purchase", "domain_option_3_price",
    "website_url", "email_sent_date", "response_date", "notes",
    "draft_url_1", "draft_url_2", "draft_url_3", "draft_url_4",
    "chosen_template", "next_action", "next_action_date",
    "acquisition_source",
]


def col_letter(n: int) -> str:
    """Convert 1-based column number to Excel-style letter."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def migrate():
    sheet_url = os.getenv("LEADS_SHEET_URL", "")
    if not sheet_url:
        print("Error: LEADS_SHEET_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()
    client = gspread.authorize(creds)

    if "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        sheet_id = sheet_url

    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    print(f"Opened sheet: {spreadsheet.title}")
    print(f"URL: {spreadsheet.url}")

    # Read all data
    all_data = worksheet.get_all_values()
    if not all_data:
        print("Sheet is empty, nothing to migrate.")
        return

    header = all_data[0]
    data_rows = all_data[1:]
    print(f"Found {len(data_rows)} data rows with {len(header)} columns")

    # Detect current schema by checking if it already matches the new one
    if len(header) >= 42 and header[22] == "domain_option_1_purchase":
        print("Sheet already has the 42-column schema. No migration needed.")
        return

    # Build mapping: for each old column, find where it goes in the new schema
    # old_col_index -> new_col_index
    old_to_new = {}
    for old_idx, col_name in enumerate(OLD_COLUMNS):
        if old_idx < len(header):
            new_idx = NEW_COLUMNS.index(col_name)
            old_to_new[old_idx] = new_idx

    print(f"\nColumn mapping (old -> new):")
    for old_idx in sorted(old_to_new.keys()):
        new_idx = old_to_new[old_idx]
        name = OLD_COLUMNS[old_idx] if old_idx < len(OLD_COLUMNS) else f"col_{old_idx}"
        if old_idx != new_idx:
            print(f"  {name}: col {old_idx + 1} -> col {new_idx + 1}  (SHIFTED)")
        else:
            print(f"  {name}: col {old_idx + 1} -> col {new_idx + 1}")

    # Also check for any extra columns beyond the old schema (manual additions)
    extra_cols = len(header) - len(OLD_COLUMNS)
    if extra_cols > 0:
        print(f"\nNote: {extra_cols} extra columns found beyond expected 35. These will be preserved at the end.")

    # Remap all data rows
    new_rows = []
    for row in data_rows:
        new_row = [""] * len(NEW_COLUMNS)
        for old_idx, new_idx in old_to_new.items():
            if old_idx < len(row):
                new_row[new_idx] = row[old_idx]

        # Set acquisition_source based on status
        acq_idx = NEW_COLUMNS.index("acquisition_source")
        if not new_row[acq_idx]:
            status_idx = NEW_COLUMNS.index("status")
            status = new_row[status_idx]
            if status == "registered_no_code":
                new_row[acq_idx] = "organic"
            elif status:  # any other status = scraped lead
                new_row[acq_idx] = "outreach"

        new_rows.append(new_row)

    # Confirm before writing
    print(f"\nReady to migrate:")
    print(f"  - Rewrite header: {len(OLD_COLUMNS)} cols -> {len(NEW_COLUMNS)} cols")
    print(f"  - Remap {len(new_rows)} data rows")
    print(f"  - Set acquisition_source for all existing leads")
    response = input("\nProceed? (y/n): ").strip().lower()
    if response != "y":
        print("Aborted.")
        return

    # Clear the sheet and rewrite everything
    print("\nClearing sheet...")
    end_col = col_letter(max(len(header), len(NEW_COLUMNS)))
    end_row = len(all_data) + 5  # extra buffer
    worksheet.batch_clear([f"A1:{end_col}{end_row}"])
    time.sleep(1)

    # Write new header
    print("Writing new header...")
    worksheet.update(values=[NEW_COLUMNS], range_name="A1")
    time.sleep(1)

    # Write data rows in batches (Google API limit)
    if new_rows:
        BATCH_SIZE = 500
        for i in range(0, len(new_rows), BATCH_SIZE):
            batch = new_rows[i:i + BATCH_SIZE]
            start_row = i + 2  # row 1 = header
            end_row = start_row + len(batch) - 1
            end_col = col_letter(len(NEW_COLUMNS))
            range_name = f"A{start_row}:{end_col}{end_row}"
            print(f"  Writing rows {start_row}-{end_row}...")
            worksheet.update(values=batch, range_name=range_name)
            time.sleep(1)

    # Re-apply header formatting
    print("Applying header formatting...")
    end_col = col_letter(len(NEW_COLUMNS))

    # Bold + freeze
    worksheet.format(f"A1:{end_col}1", {
        "textFormat": {"bold": True, "fontSize": 10},
    })
    worksheet.freeze(rows=1)

    # Color-code sections
    color_ranges = [
        ((1, 3), {"red": 0.90, "green": 0.90, "blue": 0.90}),    # Metadata: grey
        ((4, 13), {"red": 0.85, "green": 0.92, "blue": 1.0}),     # Business: blue
        ((14, 20), {"red": 0.85, "green": 1.0, "blue": 0.85}),    # Contacts: green
        ((21, 34), {"red": 1.0, "green": 0.97, "blue": 0.80}),    # Status: yellow
        ((35, 42), {"red": 0.93, "green": 0.87, "blue": 1.0}),    # Tracking: purple
    ]
    for (start, end), color in color_ranges:
        s = col_letter(start)
        e = col_letter(end)
        try:
            worksheet.format(f"{s}1:{e}1", {"backgroundColor": color})
        except Exception:
            pass

    print(f"\nMigration complete!")
    print(f"  - Header: {len(NEW_COLUMNS)} columns")
    print(f"  - Data rows: {len(new_rows)}")
    print(f"  - Sheet URL: {spreadsheet.url}")


if __name__ == "__main__":
    migrate()
