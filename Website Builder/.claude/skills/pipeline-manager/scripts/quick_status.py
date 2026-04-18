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
    python3 quick_status.py --breakdown contact
    python3 quick_status.py --breakdown city
    python3 quick_status.py --breakdown source
    python3 quick_status.py --breakdown category
    python3 quick_status.py --breakdown status
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
    "scraped_at": 1,
    "search_query": 2,
    "business_name": 3,
    "category": 4,
    "city": 6,
    "phone": 9,
    "owner_email": 14,
    "emails": 16,
    "status": 20,
    "acquisition_source": 28,
    "email_sent_date": 31,
    "next_action": 39,
    "next_action_date": 40,
    "whatsapp_sent_date": 42,
    "whatsapp_status": 43,
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

    # Contact availability breakdown (always included)
    has_email   = sum(1 for r in rows if get_cell(r, "owner_email") or get_cell(r, "emails"))
    has_phone   = sum(1 for r in rows if get_cell(r, "phone"))
    has_both    = sum(1 for r in rows if (get_cell(r, "owner_email") or get_cell(r, "emails")) and get_cell(r, "phone"))
    has_neither = sum(1 for r in rows if not get_cell(r, "owner_email") and not get_cell(r, "emails") and not get_cell(r, "phone"))

    result = {
        "total_leads": total,
        "by_status": dict(status_counts),
        "contacts": {
            "has_email": has_email,
            "has_phone": has_phone,
            "has_both": has_both,
            "email_only": has_email - has_both,
            "phone_only": has_phone - has_both,
            "has_neither": has_neither,
        },
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
        print(f"\nContact availability:")
        print(f"  Has email:   {has_email:3d} ({has_email*100//total if total else 0}%)")
        print(f"  Has phone:   {has_phone:3d} ({has_phone*100//total if total else 0}%)")
        print(f"  Has both:    {has_both:3d}")
        print(f"  Has neither: {has_neither:3d}")
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


def run_breakdown(dimension: str, rows: list, output_format: str = "json"):
    """
    Break down leads by a given dimension.

    dimension: 'contact' | 'status' | 'city' | 'source' | 'category'
    """
    result = {}

    if dimension == "contact":
        groups = {
            "has_email_and_phone": [],
            "email_only": [],
            "phone_only": [],
            "has_neither": [],
        }
        for r in rows:
            has_e = bool(get_cell(r, "owner_email") or get_cell(r, "emails"))
            has_p = bool(get_cell(r, "phone"))
            name  = get_cell(r, "business_name")
            email = get_cell(r, "owner_email") or get_cell(r, "emails")
            phone = get_cell(r, "phone")
            city  = get_cell(r, "city")
            status = get_cell(r, "status")
            entry = {"name": name, "email": email, "phone": phone, "city": city, "status": status}
            if has_e and has_p:
                groups["has_email_and_phone"].append(entry)
            elif has_e:
                groups["email_only"].append(entry)
            elif has_p:
                groups["phone_only"].append(entry)
            else:
                groups["has_neither"].append(entry)

        result = {
            "summary": {k: len(v) for k, v in groups.items()},
            "groups": groups,
        }

    else:
        # Generic group-by (status, city, source, category)
        col_map = {
            "status": "status",
            "city": "city",
            "source": "acquisition_source",
            "category": "category",
        }
        col = col_map.get(dimension, dimension)
        groups: dict[str, list] = {}
        for r in rows:
            key = get_cell(r, col) or "(empty)"
            entry = {
                "name": get_cell(r, "business_name"),
                "city": get_cell(r, "city"),
                "status": get_cell(r, "status"),
                "email": get_cell(r, "owner_email") or get_cell(r, "emails"),
                "phone": get_cell(r, "phone"),
            }
            groups.setdefault(key, []).append(entry)

        result = {
            "dimension": dimension,
            "summary": {k: len(v) for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))},
            "groups": groups,
        }

    if output_format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if dimension == "contact":
            summary = result["summary"]
            print(f"\nContact breakdown ({sum(summary.values())} leads)")
            print(f"{'='*40}")
            print(f"  Email + phone:  {summary['has_email_and_phone']:3d}")
            print(f"  Email only:     {summary['email_only']:3d}")
            print(f"  Phone only:     {summary['phone_only']:3d}")
            print(f"  Neither:        {summary['has_neither']:3d}")
            print(f"\nLeads WITH email ({summary['has_email_and_phone'] + summary['email_only']}):")
            for g in ["has_email_and_phone", "email_only"]:
                for lead in result["groups"][g]:
                    print(f"  [{lead['status']:18s}] {lead['name'][:35]:<35} {lead['email']}")
        else:
            print(f"\nBreakdown by {dimension}:")
            print(f"{'='*40}")
            for key, count in result["summary"].items():
                print(f"  {key:30s} {count:3d}")

    return result


def _load_rows():
    """Open the sheet and return raw rows (list of lists, no header)."""
    sheet_id = LEADS_SHEET_ID
    if CANONICAL_SHEET_URL and "/d/" in CANONICAL_SHEET_URL:
        sheet_id = CANONICAL_SHEET_URL.split("/d/")[1].split("/")[0]
    creds = get_credentials()
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(sheet_id).sheet1
    all_data = worksheet.get_all_values()
    return all_data[1:] if len(all_data) > 1 else []


def main():
    parser = argparse.ArgumentParser(description="Quick pipeline status check (read-only)")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    parser.add_argument(
        "--breakdown",
        choices=["contact", "status", "city", "source", "category"],
        help="Break down leads by this dimension instead of showing full status",
    )
    args = parser.parse_args()

    if args.breakdown:
        rows = _load_rows()
        run_breakdown(args.breakdown, rows, output_format=args.format)
    else:
        quick_status(output_format=args.format)


if __name__ == "__main__":
    main()
