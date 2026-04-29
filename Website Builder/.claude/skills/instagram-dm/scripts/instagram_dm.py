#!/usr/bin/env python3
"""
Instagram DM Outreach — List IG leads and generate ready-to-send German DMs.

Reads the Google Sheet, filters leads that have an Instagram URL but no email,
and prints a clean list: business name, Instagram link, and copy-paste DM text.

Usage:
    python3 instagram_dm.py               # All IG-only leads (no email)
    python3 instagram_dm.py --all-ig      # All leads with IG (even those with email)
    python3 instagram_dm.py --status website_created  # Filter by status
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

import gspread
from dotenv import load_dotenv
load_dotenv()

from execution.google_auth import get_credentials

SHEET_ID = os.getenv("LEADS_SHEET_ID", "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50")


def get_sheet_client():
    creds = get_credentials()
    return gspread.authorize(creds)


# ── DM generation ─────────────────────────────────────────────────────────────

def generate_dm(business_name: str, owner_name: str, draft_url_1: str) -> str:
    """Generate a personalized German Instagram DM."""
    greeting = f"Hallo {owner_name}" if owner_name and owner_name.strip() else f"Hallo"

    if draft_url_1 and draft_url_1.strip():
        # We have a draft website ready
        msg = (
            f"{greeting} 👋\n\n"
            f"Ich bin Louise von freshnew.ch — ich helfe kleinen Betrieben in der Schweiz zu einer professionellen Website.\n\n"
            f"Ich habe für {business_name} eine Musterseite erstellt — kostenlos, damit Sie sehen können, wie das aussehen würde:\n"
            f"👉 {draft_url_1}\n\n"
            f"Gefällt Ihnen der Stil? Ich würde mich freuen, Ihnen mehr Varianten zu zeigen.\n\n"
            f"Liebe Grüsse,\nLouise"
        )
    else:
        # No draft yet — softer intro
        msg = (
            f"{greeting} 👋\n\n"
            f"Ich bin Louise von freshnew.ch — ich helfe kleinen Betrieben in der Schweiz zu einer professionellen Website.\n\n"
            f"Ich würde gerne eine Musterseite für {business_name} erstellen — kostenlos, damit Sie sehen können, wie das aussehen würde.\n\n"
            f"Hätten Sie Interesse?\n\n"
            f"Liebe Grüsse,\nLouise"
        )
    return msg


def main():
    parser = argparse.ArgumentParser(description="Instagram DM outreach list")
    parser.add_argument("--all-ig", action="store_true",
                        help="Include leads with both Instagram AND email (default: IG-only)")
    parser.add_argument("--status", default=None,
                        help="Filter by pipeline status (e.g. website_created, new)")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    client = get_sheet_client()
    sheet = client.open_by_key(SHEET_ID).sheet1
    all_values = sheet.get_all_values()
    if not all_values:
        print("Sheet is empty.")
        return
    headers = all_values[0]
    rows = [dict(zip(headers, row)) for row in all_values[1:] if any(row)]

    leads = []
    for row in rows:
        ig = (row.get("instagram") or "").strip()
        email = (row.get("owner_email") or "").strip()
        status = (row.get("status") or "").strip()

        if not ig:
            continue
        if not args.all_ig and email:
            continue  # Skip if they have an email (use cold-email instead)
        if args.status and status != args.status:
            continue

        leads.append({
            "business_name": row.get("business_name", ""),
            "owner_name": row.get("owner_name", ""),
            "city": row.get("city", ""),
            "instagram": ig,
            "draft_url_1": (
                row.get("draft_url_1_earlydog")
                or row.get("draft_url_1")
                or row.get("url_earlydog")
                or ""
            ).strip(),
            "status": status,
            "phone": row.get("phone", ""),
        })

    if not leads:
        filter_desc = "IG-only" if not args.all_ig else "all-IG"
        status_desc = f" with status '{args.status}'" if args.status else ""
        print(f"No {filter_desc} leads found{status_desc}.")
        return

    if args.format == "json":
        import json
        out = []
        for l in leads:
            dm = generate_dm(l["business_name"], l["owner_name"], l["draft_url_1"])
            out.append({**l, "dm": dm})
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    # ── Text output ──────────────────────────────────────────────────────────
    filter_label = "with IG (all)" if args.all_ig else "with Instagram only (no email)"
    status_label = f" | status: {args.status}" if args.status else ""
    print(f"\n{'='*60}")
    print(f"INSTAGRAM LEADS — {len(leads)} leads {filter_label}{status_label}")
    print(f"{'='*60}\n")

    for i, lead in enumerate(leads, 1):
        dm = generate_dm(lead["business_name"], lead["owner_name"], lead["draft_url_1"])
        has_draft = "✓ draft ready" if lead["draft_url_1"] else "✗ no draft yet"

        print(f"{'─'*60}")
        print(f"[{i}/{len(leads)}] {lead['business_name']} — {lead['city']}")
        print(f"Status : {lead['status'] or '(none)'} | {has_draft}")
        print(f"")
        print(f"Instagram → {lead['instagram']}")
        print(f"")
        print(f"DM (copy-paste):")
        print(f"┌{'─'*56}┐")
        for line in dm.split("\n"):
            print(f"│ {line:<54} │")
        print(f"└{'─'*56}┘")
        print()

    print(f"{'='*60}")
    print(f"Total: {len(leads)} Instagram leads")
    has_draft_count = sum(1 for l in leads if l["draft_url_1"])
    print(f"With draft website: {has_draft_count}/{len(leads)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
