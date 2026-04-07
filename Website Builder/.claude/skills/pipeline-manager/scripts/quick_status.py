#!/usr/bin/env python3
"""
Quick Status — Lightweight read-only pipeline status check.

Returns a compact JSON summary of the pipeline state without generating
full action items or processing leads. Much faster and cheaper than
running `pipeline_manager.py --action report`.

Usage:
    python3 quick_status.py
    python3 quick_status.py --format json
    python3 quick_status.py --format text
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from execution.google_auth import get_credentials

load_dotenv()

CANONICAL_SHEET_URL = os.getenv("LEADS_SHEET_URL", "")
LEADS_SHEET_ID = os.getenv("LEADS_SHEET_ID", "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50")

# Column indices (0-based) matching LEAD_COLUMNS
COL_IDX = {
    "lead_id": 0,
    "business_name": 3,
    "category": 4,
    "city": 6,
    "phone": 9,
    "owner_email": 14,
    "status": 20,
    "email_sent_date": 31,
    "next_action": 39,
    "next_action_date": 40,
}


def get_cell(row, col_name):
    """Safely get a cell value by column name."""
    idx = COL_IDX.get(col_name, 999)
    if idx < len(row):
        return row[idx].strip()
    return ""


def quick_status(output_format="json"):
    """Read the sheet and return a compact status summary."""
    # Open sheet
    sheet_id = LEADS_SHEET_ID
    if CANONICAL_SHEET_URL and "/d/" in CANONICAL_SHEET_URL:
        sheet_id = CANONICAL_SHEET_URL.split("/d/")[1].split("/")[0]

    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    all_data = worksheet.get_all_values()
    if len(all_data) <= 1:
        result = {"total_leads": 0, "by_status": {}, "needs_attention": [], "top_priorities": []}
        if output_format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print("No leads in sheet.")
        return result

    rows = all_data[1:]

    # Count by status
    status_counts = Counter()
    for row in rows:
        status = get_cell(row, "status").lower() or "(empty)"
        status_counts[status] += 1

    # Find leads needing attention
    needs_attention = []
    top_priorities = []
    now = datetime.now()

    for row in rows:
        status = get_cell(row, "status").lower()
        biz = get_cell(row, "business_name")
        city = get_cell(row, "city")
        email = get_cell(row, "owner_email")
        phone = get_cell(row, "phone")
        email_date_str = get_cell(row, "email_sent_date")
        label = f"{biz} ({city})" if city else biz

        if status == "email_sent" and email_date_str:
            try:
                email_date = datetime.strptime(email_date_str, "%Y-%m-%d")
                days = (now - email_date).days
                if days >= 14:
                    needs_attention.append(f"{label} — {days}d since email, send breakup")
                elif days >= 7:
                    needs_attention.append(f"{label} — {days}d since email, send follow-up")
                elif days >= 3:
                    needs_attention.append(f"{label} — {days}d since email, call {phone}")
            except ValueError:
                pass

        elif status == "responded":
            needs_attention.append(f"{label} — responded! Start onboarding")

        elif status == "website_creating":
            needs_attention.append(f"{label} — build final website + deploy")

    # Build priorities
    n_new = status_counts.get("new", 0)
    n_website_created = status_counts.get("website_created", 0)
    n_email_sent = status_counts.get("email_sent", 0)
    n_responded = status_counts.get("responded", 0)
    n_creating = status_counts.get("website_creating", 0)

    if n_responded > 0:
        top_priorities.append(f"Onboard {n_responded} responded lead(s) — they're interested!")
    if n_creating > 0:
        top_priorities.append(f"Build final website for {n_creating} lead(s)")
    overdue = [a for a in needs_attention if "follow-up" in a or "breakup" in a or "call" in a]
    if overdue:
        top_priorities.append(f"Follow up with {len(overdue)} overdue lead(s)")
    if n_website_created > 0:
        top_priorities.append(f"Send cold emails to {n_website_created} lead(s) with websites ready")
    if n_new > 0:
        top_priorities.append(f"Process {n_new} new lead(s) (build + deploy drafts)")

    # Conversion funnel
    total = len(rows)
    emails_out = sum(1 for row in rows if get_cell(row, "email_sent_date"))
    sold = status_counts.get("sold", 0)

    result = {
        "total_leads": total,
        "by_status": dict(status_counts),
        "needs_attention": needs_attention[:10],
        "top_priorities": top_priorities[:5],
        "funnel": {
            "total": total,
            "emails_sent": emails_out,
            "responded": n_responded,
            "sold": sold,
        },
    }

    if output_format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"\nPipeline Status — {total} leads")
        print(f"{'='*40}")
        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            print(f"  {status:25s} {count:3d}")
        if top_priorities:
            print(f"\nTop Priorities:")
            for i, p in enumerate(top_priorities, 1):
                print(f"  {i}. {p}")
        if needs_attention:
            print(f"\nNeeds Attention:")
            for item in needs_attention[:5]:
                print(f"  - {item}")
        print(f"\nFunnel: {total} leads → {emails_out} emails → {n_responded} responded → {sold} sold")

    return result


def main():
    parser = argparse.ArgumentParser(description="Quick pipeline status check (read-only)")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    args = parser.parse_args()

    quick_status(output_format=args.format)


if __name__ == "__main__":
    main()
