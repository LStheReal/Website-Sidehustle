#!/usr/bin/env python3
"""
Clean up the leads Google Sheet by removing unusable leads:
1. Leads with NO email AND NO phone number (no way to contact them)
2. Leads with emails from personal website domains (not real email providers)

Usage:
    cd "Website Builder"
    source .venv/bin/activate
    python3 .claude/skills/scrape-no-website-leads/scripts/clean_leads.py
    python3 .claude/skills/scrape-no-website-leads/scripts/clean_leads.py --dry-run
"""

import os
import sys
import argparse

# Add project root to path for shared utilities
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
sys.path.insert(0, PROJECT_ROOT)
from execution.google_auth import get_credentials
from dotenv import load_dotenv

import gspread

load_dotenv()

# Known email providers — emails from these domains are legitimate
EMAIL_PROVIDERS = {
    # Global
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "hotmail.ch", "hotmail.de", "hotmail.fr", "hotmail.it",
    "live.com", "live.ch", "live.de", "msn.com",
    "yahoo.com", "yahoo.de", "yahoo.fr", "yahoo.it", "yahoo.co.uk", "yahoo.ch",
    "ymail.com", "rocketmail.com",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "pm.me",
    "aol.com",
    "zoho.com",
    "mail.com",
    "email.com",
    "yandex.com", "yandex.ru",
    "tutanota.com", "tuta.io",
    "fastmail.com",
    "hey.com",
    "gmx.com",
    # Swiss
    "gmx.ch", "gmx.net", "gmx.de", "gmx.at",
    "bluewin.ch",
    "sunrise.ch",
    "hispeed.ch",
    "swissonline.ch",
    "vtxnet.ch",
    "green.ch",
    "quickline.ch",
    "init7.net",
    "salt.ch",
    "wingo.ch",
    "yallo.ch",
    "hin.ch",
    "swisscom.ch",
    "besonet.ch",
    "mypage.ch",
    "netplus.ch",
    "tiscali.ch",
    # German
    "web.de", "t-online.de", "freenet.de", "posteo.de", "mailbox.org",
    "arcor.de", "online.de", "vodafone.de", "1und1.de",
    # French
    "orange.fr", "free.fr", "sfr.fr", "laposte.net", "wanadoo.fr",
    # Italian
    "libero.it", "virgilio.it", "tin.it", "alice.it", "tiscali.it",
    # Austrian
    "a1.net", "chello.at", "aon.at",
}


def is_email_provider(email: str) -> bool:
    """Check if an email address is from a known email provider."""
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().split("@")[-1]
    return domain in EMAIL_PROVIDERS


def extract_emails_from_cell(cell_value: str) -> list[str]:
    """Extract all email addresses from a cell value (may be comma-separated or JSON-like)."""
    if not cell_value:
        return []
    # Clean up brackets and quotes
    cleaned = cell_value.strip().strip("[]").replace("'", "").replace('"', '')
    # Split by comma or semicolon
    parts = [p.strip() for p in cleaned.replace(";", ",").split(",")]
    return [p for p in parts if "@" in p]


def has_valid_contact(row: list[str], col_indices: dict) -> bool:
    """Check if a lead has at least one valid way to contact them (email or phone)."""
    phone = row[col_indices["phone"]].strip() if col_indices["phone"] < len(row) else ""
    owner_email = row[col_indices["owner_email"]].strip() if col_indices["owner_email"] < len(row) else ""
    emails = row[col_indices["emails"]].strip() if col_indices["emails"] < len(row) else ""
    owner_phone = row[col_indices["owner_phone"]].strip() if col_indices["owner_phone"] < len(row) else ""

    # Has phone number?
    if phone or owner_phone:
        return True

    # Has any email?
    all_emails = extract_emails_from_cell(owner_email) + extract_emails_from_cell(emails)
    if any(e for e in all_emails):
        return True

    return False


def has_only_personal_website_emails(row: list[str], col_indices: dict) -> bool:
    """
    Check if ALL emails for this lead are from personal website domains (not email providers).
    Returns True if the lead should be REMOVED (has emails but none from real providers).
    Returns False if the lead has no emails at all (handled by has_valid_contact).
    """
    owner_email = row[col_indices["owner_email"]].strip() if col_indices["owner_email"] < len(row) else ""
    emails_cell = row[col_indices["emails"]].strip() if col_indices["emails"] < len(row) else ""

    all_emails = extract_emails_from_cell(owner_email) + extract_emails_from_cell(emails_cell)

    if not all_emails:
        return False  # No emails — not this filter's job

    # Check if ANY email is from a known provider
    for email in all_emails:
        if is_email_provider(email):
            return False  # At least one legit provider email

    return True  # All emails are from personal/business website domains


def clean_leads_sheet(dry_run: bool = False):
    """Clean the leads sheet by removing unusable leads."""
    sheet_id = os.getenv("LEADS_SHEET_ID", "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50")
    sheet_url = os.getenv("LEADS_SHEET_URL", "")

    if sheet_url and "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]

    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    all_data = worksheet.get_all_values()
    if not all_data:
        print("Sheet is empty")
        return

    headers = all_data[0]
    rows = all_data[1:]

    print(f"Sheet: {spreadsheet.title}")
    print(f"Total leads: {len(rows)}")
    print(f"Columns: {len(headers)}")

    # Build column index map
    col_indices = {}
    for col_name in ["phone", "owner_email", "owner_phone", "emails", "business_name", "city"]:
        try:
            col_indices[col_name] = headers.index(col_name)
        except ValueError:
            print(f"WARNING: Column '{col_name}' not found in sheet headers")
            col_indices[col_name] = 999  # Will be out of range

    # Analyze each row
    rows_to_delete = []  # (row_index_1based, reason, business_name)

    for i, row in enumerate(rows):
        row_num = i + 2  # 1-based, skip header
        biz_name = row[col_indices["business_name"]] if col_indices["business_name"] < len(row) else "?"
        city = row[col_indices["city"]] if col_indices["city"] < len(row) else ""

        # Check 1: No contact info at all
        if not has_valid_contact(row, col_indices):
            rows_to_delete.append((row_num, "no_contact", biz_name, city))
            continue

        # Check 2: Any non-provider emails → remove regardless of phone
        if has_only_personal_website_emails(row, col_indices):
            owner_email = row[col_indices["owner_email"]].strip() if col_indices["owner_email"] < len(row) else ""
            emails_cell = row[col_indices["emails"]].strip() if col_indices["emails"] < len(row) else ""
            sample_email = owner_email or emails_cell
            rows_to_delete.append((row_num, f"personal_website_email ({sample_email})", biz_name, city))
            continue

    # Report
    no_contact = sum(1 for _, r, _, _ in rows_to_delete if r == "no_contact")
    personal_email = sum(1 for _, r, _, _ in rows_to_delete if r.startswith("personal_website"))

    print(f"\n{'='*60}")
    print(f"LEADS TO REMOVE: {len(rows_to_delete)}")
    print(f"  No contact info (no email, no phone): {no_contact}")
    print(f"  Personal website emails only (no phone): {personal_email}")
    print(f"  Keeping: {len(rows) - len(rows_to_delete)}")
    print(f"{'='*60}")

    if rows_to_delete:
        print(f"\nLeads to remove:")
        for row_num, reason, biz_name, city in rows_to_delete:
            print(f"  Row {row_num}: {biz_name} ({city}) — {reason}")

    if dry_run:
        print(f"\n[DRY RUN] No changes made. Run without --dry-run to delete.")
        return

    if not rows_to_delete:
        print("\nNothing to clean up!")
        return

    # Delete rows from bottom to top so indices don't shift
    rows_to_delete.sort(key=lambda x: x[0], reverse=True)

    print(f"\nDeleting {len(rows_to_delete)} rows...")
    for row_num, reason, biz_name, _ in rows_to_delete:
        worksheet.delete_rows(row_num)
        print(f"  Deleted row {row_num}: {biz_name}")

    print(f"\nDone! Removed {len(rows_to_delete)} unusable leads.")


def main():
    parser = argparse.ArgumentParser(description="Clean unusable leads from Google Sheet")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without deleting")
    args = parser.parse_args()

    clean_leads_sheet(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
