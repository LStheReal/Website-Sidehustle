#!/usr/bin/env python3
"""
Pipeline Manager — Orchestrator for the Website Builder pipeline.

Coordinates all skills, reads lead status from Google Sheets,
runs automated steps, and generates action items for the human.

Actions:
  report      — Show pipeline status overview + action items
  process     — Process ALL leads through their next automated step
  process-one — Process a single lead (by --lead-id)

Usage:
  python3 pipeline_manager.py --sheet-url "..." --action report
  python3 pipeline_manager.py --sheet-url "..." --action process --sender-name "..." --sender-phone "..." --sender-email "..."
  python3 pipeline_manager.py --sheet-url "..." --action process-one --lead-id "abc123" --sender-name "..." --sender-phone "..." --sender-email "..."
"""

import argparse
import difflib
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from dotenv import load_dotenv

# --- Path setup ---
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from execution.google_auth import get_credentials
from execution.utils import save_intermediate

load_dotenv()

# Canonical sheet URL — set in .env as LEADS_SHEET_URL
CANONICAL_SHEET_URL = os.getenv("LEADS_SHEET_URL", "")

# --- Skill imports ---
# Add skill script directories to path for direct imports

SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"

# Cold email
sys.path.insert(0, str(SKILLS_DIR / "cold-email" / "scripts"))
from generate_cold_email import (
    generate_day0_email,
    generate_day7_email,
    generate_day14_email,
    get_screenshot_url,
    send_email,
    capture_screenshot_bytes,
)

# Call assistant
sys.path.insert(0, str(SKILLS_DIR / "call-assistant" / "scripts"))
from generate_call_script import generate_call_script

# WhatsApp outreach
sys.path.insert(0, str(SKILLS_DIR / "whatsapp-outreach" / "scripts"))
from send_whatsapp import generate_for_lead as generate_whatsapp_for_lead, format_swiss_phone

# Write email (general)
sys.path.insert(0, str(SKILLS_DIR / "write-email" / "scripts"))
from generate_email import GENERATORS as EMAIL_GENERATORS

# Find domain
sys.path.insert(0, str(SKILLS_DIR / "find-domain" / "scripts"))
from find_domain import find_domains

# Deploy website
sys.path.insert(0, str(SKILLS_DIR / "deploy-website" / "scripts"))
from deploy_website import (
    validate_site_dir,
    sanitize_project_name,
    check_wrangler_auth,
    create_project,
    deploy_site,
)

# Build website generators — each has a generate_website.py with the same function name,
# so we use importlib to avoid shadowing
def _import_build_function(template_name: str):
    """Import generate_website from a specific template's scripts."""
    script_path = SKILLS_DIR / f"build-website-{template_name}" / "scripts" / "generate_website.py"
    spec = importlib.util.spec_from_file_location(f"build_{template_name}", str(script_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_website

build_earlydog = _import_build_function("earlydog")
build_bia = _import_build_function("bia")
build_liveblocks = _import_build_function("liveblocks")
build_loveseen = _import_build_function("loveseen")

BUILD_FUNCTIONS = {
    "earlydog": build_earlydog,
    "bia": build_bia,
    "liveblocks": build_liveblocks,
    "loveseen": build_loveseen,
}

TEMPLATE_LABELS = {
    "earlydog": "Klassisch",
    "bia": "Modern",
    "liveblocks": "Frisch",
    "loveseen": "Elegant",
}


# --- Google Sheet column indices (1-based, matching LEAD_COLUMNS in update_sheet.py) ---

# Column indices (1-based) — MUST match LEAD_COLUMNS in update_sheet.py (42 columns)
COL = {
    "lead_id": 1,
    "scraped_at": 2,
    "search_query": 3,
    "business_name": 4,
    "category": 5,
    "address": 6,
    "city": 7,
    "state": 8,
    "zip_code": 9,
    "phone": 10,
    "google_maps_url": 11,
    "rating": 12,
    "review_count": 13,
    "owner_name": 14,
    "owner_email": 15,
    "owner_phone": 16,
    "emails": 17,
    "facebook": 18,
    "instagram": 19,
    "linkedin": 20,
    "status": 21,
    "domain_option_1": 22,
    "domain_option_1_purchase": 23,
    "domain_option_1_price": 24,
    "domain_option_2": 25,
    "domain_option_2_purchase": 26,
    "domain_option_2_price": 27,
    "domain_option_3": 28,
    "domain_option_3_purchase": 29,
    "domain_option_3_price": 30,
    "website_url": 31,
    "email_sent_date": 32,
    "response_date": 33,
    "notes": 34,
    "draft_url_1": 35,
    "draft_url_2": 36,
    "draft_url_3": 37,
    "draft_url_4": 38,
    "chosen_template": 39,
    "next_action": 40,
    "next_action_date": 41,
    "acquisition_source": 42,
    "whatsapp_sent_date": 43,
    "whatsapp_status": 44,
}

COLUMN_NAMES = list(COL.keys())


# --- Sheet helpers ---

def open_sheet(sheet_url: str):
    """Open a Google Sheet and return (spreadsheet, worksheet)."""
    creds = get_credentials()
    client = gspread.authorize(creds)

    if "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        sheet_id = sheet_url

    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1
    return spreadsheet, worksheet


def read_all_leads(worksheet) -> list[dict]:
    """Read all leads from the sheet as a list of dicts."""
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1:
        return []

    headers = all_values[0]
    leads = []
    for row in all_values[1:]:
        lead = {}
        for i, col_name in enumerate(COLUMN_NAMES):
            if i < len(row):
                lead[col_name] = row[i]
            else:
                lead[col_name] = ""
        # Also store the raw row index (1-based, accounting for header)
        lead["_row_idx"] = all_values.index(row) + 1 if row in all_values else None
        leads.append(lead)

    # Fix _row_idx properly
    for idx, lead in enumerate(leads):
        lead["_row_idx"] = idx + 2  # +2 because row 1 is header, and idx is 0-based

    return leads


def find_lead_by_name(worksheet, search_name: str) -> list[dict]:
    """
    Fuzzy-match a business name against all leads in the sheet.

    Returns list of matching leads (best matches first), each with
    lead_id, business_name, city, status, and match_score.
    """
    leads = read_all_leads(worksheet)
    if not leads:
        return []

    names = [l.get("business_name", "") for l in leads]
    # Try exact substring match first
    exact = []
    for lead in leads:
        biz = lead.get("business_name", "")
        if search_name.lower() in biz.lower():
            exact.append({
                "lead_id": lead.get("lead_id", ""),
                "business_name": biz,
                "city": lead.get("city", ""),
                "status": lead.get("status", ""),
                "match_score": 1.0,
            })

    if exact:
        return exact

    # Fuzzy match
    close = difflib.get_close_matches(search_name, names, n=5, cutoff=0.4)
    results = []
    for match_name in close:
        for lead in leads:
            if lead.get("business_name") == match_name:
                score = difflib.SequenceMatcher(None, search_name.lower(), match_name.lower()).ratio()
                results.append({
                    "lead_id": lead.get("lead_id", ""),
                    "business_name": match_name,
                    "city": lead.get("city", ""),
                    "status": lead.get("status", ""),
                    "match_score": round(score, 2),
                })
                break

    return results


def update_cells(worksheet, row_idx: int, updates: dict):
    """
    Update multiple cells in a row.

    Args:
        worksheet: gspread Worksheet.
        row_idx: 1-based row index.
        updates: Dict of {column_name: value}.
    """
    from gspread.utils import rowcol_to_a1

    cells = []
    for col_name, value in updates.items():
        col_idx = COL[col_name]
        cell_ref = rowcol_to_a1(row_idx, col_idx)
        cells.append({"range": cell_ref, "values": [[value]]})

    if cells:
        worksheet.batch_update(cells, value_input_option="USER_ENTERED")


# --- Business data helpers ---

def lead_to_website_data(lead: dict) -> dict:
    """Convert a lead dict to the business data format expected by website builders."""
    business_name = lead.get("business_name", "")
    category = lead.get("category", "")
    city = lead.get("city", "")
    phone = lead.get("phone", "")
    address = lead.get("address", "")
    email = lead.get("owner_email", "") or lead.get("emails", "")

    return {
        "BUSINESS_NAME": business_name,
        "TAGLINE": f"{category} in {city}" if category and city else "",
        "PHONE": phone,
        "EMAIL": email,
        "ADDRESS": address,
    }


def get_template_order(category: str) -> list[str]:
    """
    Determine template build order based on business category.
    All 3 are always built, but the order determines labels.

    Trade/manual → earlydog first, Professional → bia first, Tech → liveblocks first.
    """
    cat = category.lower() if category else ""

    trade_keywords = ["reinigung", "maler", "sanitär", "sanitaer", "gärtner", "gaertner",
                      "elektriker", "schreiner", "dachdecker", "zimmermann", "schlosser",
                      "spengler", "coiffeur", "friseur", "bäckerei", "baeckerei", "metzgerei"]
    pro_keywords = ["architekt", "anwalt", "berater", "treuhand", "steuer", "notar",
                    "arzt", "zahnarzt", "praxis", "kanzlei", "immobilien"]
    tech_keywords = ["it", "software", "marketing", "design", "agentur", "digital",
                     "web", "consulting", "medien"]

    if any(kw in cat for kw in trade_keywords):
        return ["earlydog", "bia", "liveblocks", "loveseen"]
    elif any(kw in cat for kw in pro_keywords):
        return ["bia", "earlydog", "liveblocks", "loveseen"]
    elif any(kw in cat for kw in tech_keywords):
        return ["liveblocks", "bia", "earlydog", "loveseen"]
    else:
        return ["earlydog", "bia", "liveblocks", "loveseen"]


# --- Pipeline processing per status ---

def process_new(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process a 'new' lead: build 3 website drafts, deploy, generate outreach.
    Returns list of action items for the human.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    category = lead.get("category", "")
    city = lead.get("city", "")

    print(f"\n{'='*60}")
    print(f"  Processing NEW: {biz}")
    print(f"{'='*60}")

    # Step 1: Build 3 website drafts
    website_data = lead_to_website_data(lead)
    template_order = get_template_order(category)
    draft_urls = {}

    for t_idx, template_name in enumerate(template_order):
        # Delay between deployments to avoid Cloudflare rate limits
        if t_idx > 0:
            time.sleep(15)

        print(f"\n  Building {template_name} template...")
        output_dir = str(PROJECT_ROOT / ".tmp" / f"draft_{lead_id}_{template_name}")

        try:
            build_fn = BUILD_FUNCTIONS[template_name]
            result = build_fn(website_data, output_dir, overwrite=True)
            print(f"    Built: {result['output_dir']}")

            # Step 2: Deploy to Cloudflare Pages
            project_name = sanitize_project_name(f"{biz}-{template_name}")
            print(f"    Deploying as '{project_name}'...")

            if not check_wrangler_auth():
                print("    WARNING: Wrangler not authenticated. Run 'npx wrangler login' first.")
                actions.append({
                    "type": "SETUP",
                    "priority": "HIGH",
                    "business": biz,
                    "message": "Wrangler not authenticated. Run 'npx wrangler login' before processing.",
                })
                break

            create_project(project_name)
            live_url = deploy_site(Path(output_dir), project_name)

            if live_url:
                draft_urls[template_name] = live_url
                print(f"    Deployed: {live_url}")
            else:
                print(f"    WARNING: Deploy failed for {template_name}")

        except Exception as e:
            print(f"    ERROR building {template_name}: {e}")

    # Step 3: Update sheet with draft URLs
    sheet_updates = {"status": "website_created"}

    url_cols = ["draft_url_1", "draft_url_2", "draft_url_3", "draft_url_4"]
    for i, template_name in enumerate(template_order):
        if template_name in draft_urls and i < 4:
            sheet_updates[url_cols[i]] = draft_urls[template_name]

    # Step 4: Update next actions
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()

    if owner_email:
        sheet_updates["next_action"] = f"READY TO SEND EMAIL"
        actions.append({
            "type": "READY_FOR_OUTREACH",
            "priority": "LOW",
            "business": biz,
            "message": f"Website built for {biz}. Run action send-emails to send cold email.",
        })
    else:
        phone = lead.get("phone", "")
        sheet_updates["next_action"] = f"READY TO CALL"
        actions.append({
            "type": "READY_FOR_OUTREACH",
            "priority": "LOW",
            "business": biz,
            "message": f"Website built for {biz}. No email found, ready for call.",
        })

    # Write all updates to sheet
    update_cells(worksheet, row_idx, sheet_updates)
    print(f"  Sheet updated: status → website_created")

    return actions


def process_website_created(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process a 'website_created' lead: generate outreach if not already done.
    Returns list of action items.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    category = lead.get("category", "")
    city = lead.get("city", "")
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()

    # Get draft URLs from sheet
    url1 = lead.get("draft_url_1", "")
    url2 = lead.get("draft_url_2", "")
    url3 = lead.get("draft_url_3", "")
    url4 = lead.get("draft_url_4", "")
    if not url4:
        url4 = url3 or url2 or url1

    if not any([url1, url2, url3, url4]):
        actions.append({
            "type": "WARNING",
            "priority": "MEDIUM",
            "business": biz,
            "message": f"{biz}: No draft URLs found. Build + deploy first (set status to 'new' to re-process).",
        })
        return actions

    print(f"\n  Generating outreach for: {biz}")

    phone = lead.get("phone", "")

    # WhatsApp-first: all leads have phone numbers
    if phone:
        wa_result = generate_whatsapp_for_lead(lead, sender_info["name"], variant="day0")
        if "error" in wa_result:
            actions.append({
                "type": "WARNING",
                "priority": "MEDIUM",
                "business": biz,
                "message": f"{biz}: WhatsApp error: {wa_result['error']}",
            })
        else:
            actions.append({
                "type": "SEND_WHATSAPP",
                "priority": "HIGH",
                "business": biz,
                "phone": phone,
                "wa_me_link": wa_result.get("wa_me_link", ""),
                "message": f"WHATSAPP SENDEN: {biz} — {phone}",
            })

        if owner_email:
            actions.append({
                "type": "INFO",
                "priority": "LOW",
                "business": biz,
                "message": f"{biz}: Has email ({owner_email}) — Day 7 email follow-up available after WhatsApp.",
            })
    else:
        actions.append({
            "type": "WARNING",
            "priority": "HIGH",
            "business": biz,
            "message": f"{biz}: No phone number! Cannot send WhatsApp. Manual outreach needed.",
        })

    return actions


def process_email_sent(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process an 'email_sent' lead: check timing and generate follow-ups.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    category = lead.get("category", "")
    city = lead.get("city", "")
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()
    phone = lead.get("phone", "")

    # Calculate days since email
    email_date_str = lead.get("email_sent_date", "").strip()
    if not email_date_str:
        actions.append({
            "type": "WARNING",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: email_sent but no email_sent_date. Update the sheet.",
        })
        return actions

    try:
        email_date = datetime.strptime(email_date_str, "%Y-%m-%d")
    except ValueError:
        actions.append({
            "type": "WARNING",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: Invalid email_sent_date format: '{email_date_str}'. Use YYYY-MM-DD.",
        })
        return actions

    days_since = (datetime.now() - email_date).days

    # Get draft URLs for follow-up emails
    url1 = lead.get("draft_url_1", "")
    url2 = lead.get("draft_url_2", "")
    url3 = lead.get("draft_url_3", "")
    url4 = lead.get("draft_url_4", "")
    if not url4:
        url4 = url3 or url2 or url1

    sheet_updates = {}

    if days_since >= 14:
        # Day 14: Breakup email
        email = generate_day14_email(
            business_name=biz,
            owner_name=owner_name,
            lead_id=lead_id,
            sender_name=sender_info["name"],
            sender_phone=sender_info["phone"],
            sender_email=sender_info["email"],
        )
        email_result = {"generated_at": datetime.now().isoformat(), "emails": [email]}
        email_path = save_intermediate(email_result, f"breakup_email_{lead_id}")
        sheet_updates["next_action"] = f"SEND BREAKUP EMAIL ({days_since} days)"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "SEND_EMAIL",
            "priority": "MEDIUM",
            "business": biz,
            "to": owner_email,
            "days_since_email": days_since,
            "file": email_path,
            "message": f"Day {days_since}: Send breakup email to {owner_email} — {email_path}",
        })

    elif days_since >= 7:
        # Day 7: Follow-up email
        email = generate_day7_email(
            business_name=biz,
            category=category,
            owner_name=owner_name,
            url1=url1, url2=url2, url3=url3, url4=url4,
            lead_id=lead_id,
            sender_name=sender_info["name"],
            sender_phone=sender_info["phone"],
            sender_email=sender_info["email"],
        )
        email_result = {"generated_at": datetime.now().isoformat(), "emails": [email]}
        email_path = save_intermediate(email_result, f"followup_email_{lead_id}")
        sheet_updates["next_action"] = f"SEND FOLLOW-UP EMAIL ({days_since} days)"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "SEND_EMAIL",
            "priority": "HIGH",
            "business": biz,
            "to": owner_email,
            "days_since_email": days_since,
            "file": email_path,
            "message": f"Day {days_since}: Send follow-up email to {owner_email} — {email_path}",
        })

    elif days_since >= 3:
        # Day 3+: Call follow-up
        script = generate_call_script(
            business_name=biz, category=category, city=city,
            phone=phone, owner_name=owner_name,
            url1=url1, url2=url2, url3=url3,
            sender_name=sender_info["name"], email_sent=True,
        )
        script_path = save_intermediate(script, f"followup_call_{lead_id}")
        sheet_updates["next_action"] = f"CALL FOLLOW-UP ({days_since} days)"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "CALL",
            "priority": "HIGH",
            "business": biz,
            "phone": phone,
            "days_since_email": days_since,
            "file": script_path,
            "message": f"Day {days_since}: Call {biz} at {phone} for follow-up — {script_path}",
        })

    else:
        # Too early for follow-up
        next_date = (email_date + timedelta(days=3)).strftime("%Y-%m-%d")
        actions.append({
            "type": "WAIT",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: Email sent {days_since} day(s) ago. Follow-up call due on {next_date}.",
        })

    if sheet_updates:
        update_cells(worksheet, row_idx, sheet_updates)

    return actions


def process_whatsapp_sent(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process a 'whatsapp_sent' lead: Day 3 call, Day 7 email/WA follow-up, Day 14 breakup.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    category = lead.get("category", "")
    city = lead.get("city", "")
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()
    phone = lead.get("phone", "")

    # Calculate days since WhatsApp
    wa_date_str = lead.get("whatsapp_sent_date", "").strip()
    if not wa_date_str:
        actions.append({
            "type": "WARNING",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: whatsapp_sent but no whatsapp_sent_date. Update the sheet.",
        })
        return actions

    try:
        wa_date = datetime.strptime(wa_date_str, "%Y-%m-%d")
    except ValueError:
        actions.append({
            "type": "WARNING",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: Invalid whatsapp_sent_date format: '{wa_date_str}'. Use YYYY-MM-DD.",
        })
        return actions

    days_since = (datetime.now() - wa_date).days

    # Get draft URLs
    url1 = lead.get("draft_url_1", "")
    url2 = lead.get("draft_url_2", "")
    url3 = lead.get("draft_url_3", "")
    url4 = lead.get("draft_url_4", "") or url3 or url2 or url1

    sheet_updates = {}

    if days_since >= 14:
        if owner_email:
            # Day 14: Breakup email
            email = generate_day14_email(
                business_name=biz,
                owner_name=owner_name,
                lead_id=lead_id,
                sender_name=sender_info["name"],
                sender_phone=sender_info["phone"],
                sender_email=sender_info["email"],
            )
            email_path = save_intermediate({"emails": [email]}, f"breakup_email_{lead_id}")
            sheet_updates["next_action"] = f"SEND BREAKUP EMAIL ({days_since} days)"
            sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")
            actions.append({
                "type": "SEND_EMAIL",
                "priority": "MEDIUM",
                "business": biz,
                "to": owner_email,
                "days_since_whatsapp": days_since,
                "file": email_path,
                "message": f"Day {days_since}: Send breakup email to {owner_email}",
            })
        else:
            # No email — mark as closed
            sheet_updates["next_action"] = "CLOSED — no response after 14 days"
            sheet_updates["status"] = "closed_no_response"
            actions.append({
                "type": "INFO",
                "priority": "LOW",
                "business": biz,
                "message": f"{biz}: No response after {days_since} days (no email for breakup). Closed.",
            })

    elif days_since >= 7:
        if owner_email:
            # Day 7: Email follow-up
            email = generate_day7_email(
                business_name=biz,
                category=category,
                owner_name=owner_name,
                url1=url1, url2=url2, url3=url3, url4=url4,
                lead_id=lead_id,
                sender_name=sender_info["name"],
                sender_phone=sender_info["phone"],
                sender_email=sender_info["email"],
            )
            email_path = save_intermediate({"emails": [email]}, f"followup_email_{lead_id}")
            sheet_updates["next_action"] = f"SEND FOLLOW-UP EMAIL ({days_since} days)"
            sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")
            actions.append({
                "type": "SEND_EMAIL",
                "priority": "HIGH",
                "business": biz,
                "to": owner_email,
                "days_since_whatsapp": days_since,
                "file": email_path,
                "message": f"Day {days_since}: Send email follow-up to {owner_email}",
            })
        else:
            # No email — WhatsApp follow-up
            wa_result = generate_whatsapp_for_lead(lead, sender_info["name"], variant="followup")
            if "error" not in wa_result:
                sheet_updates["next_action"] = f"SEND WA FOLLOW-UP ({days_since} days)"
                sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")
                actions.append({
                    "type": "SEND_WHATSAPP",
                    "priority": "HIGH",
                    "business": biz,
                    "phone": phone,
                    "wa_me_link": wa_result.get("wa_me_link", ""),
                    "message": f"Day {days_since}: Send WhatsApp follow-up to {biz} — {phone}",
                })

    elif days_since >= 3:
        # Day 3+: Call follow-up
        script = generate_call_script(
            business_name=biz, category=category, city=city,
            phone=phone, owner_name=owner_name,
            url1=url1, url2=url2, url3=url3, url4=url4,
            sender_name=sender_info["name"], whatsapp_sent=True,
        )
        script_path = save_intermediate(script, f"followup_call_{lead_id}")
        sheet_updates["next_action"] = f"CALL FOLLOW-UP ({days_since} days since WhatsApp)"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "CALL",
            "priority": "HIGH",
            "business": biz,
            "phone": phone,
            "days_since_whatsapp": days_since,
            "file": script_path,
            "message": f"Day {days_since}: Call {biz} at {phone} for follow-up",
        })

    else:
        # Too early for follow-up
        next_date = (wa_date + timedelta(days=3)).strftime("%Y-%m-%d")
        actions.append({
            "type": "WAIT",
            "priority": "LOW",
            "business": biz,
            "message": f"{biz}: WhatsApp sent {days_since} day(s) ago. Call follow-up due on {next_date}.",
        })

    if sheet_updates:
        update_cells(worksheet, row_idx, sheet_updates)

    return actions


def process_responded(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process a 'responded' lead: generate onboarding email + find domains.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    category = lead.get("category", "")
    city = lead.get("city", "")
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()

    print(f"\n  Processing RESPONDED: {biz}")

    # Step 1: Generate onboarding email
    email_gen = EMAIL_GENERATORS["onboarding"]
    email = email_gen(
        business_name=biz, owner_name=owner_name, city=city,
        sender_name=sender_info["name"],
        sender_phone=sender_info["phone"],
        sender_email=sender_info["email"],
        context="",
    )
    email_result = {
        "generated_at": datetime.now().isoformat(),
        "email": email,
    }
    email_path = save_intermediate(email_result, f"onboarding_email_{lead_id}")

    actions.append({
        "type": "SEND_EMAIL",
        "priority": "HIGH",
        "business": biz,
        "to": owner_email,
        "subject": email["subject"],
        "file": email_path,
        "message": f"Send onboarding email to {owner_email} to collect design choice, values, logo — {email_path}",
    })

    # Step 2: Find 3 available domains
    print(f"  Finding domains for {biz}...")
    try:
        domain_result = find_domains(
            business_name=biz,
            business_type=category,
            city=city,
        )
        domain_path = save_intermediate(domain_result, f"domains_{lead_id}")

        if domain_result.get("suggestions"):
            domain_names = [s["domain"] for s in domain_result["suggestions"][:3]]
            actions.append({
                "type": "INFO",
                "priority": "LOW",
                "business": biz,
                "message": f"Domain options found: {', '.join(domain_names)}. Will be confirmed after onboarding.",
            })
        else:
            actions.append({
                "type": "WARNING",
                "priority": "LOW",
                "business": biz,
                "message": f"No available domains found for {biz}. Try different name variations later.",
            })
    except Exception as e:
        print(f"  WARNING: Domain search failed: {e}")

    # Update sheet
    sheet_updates = {
        "next_action": "SEND ONBOARDING EMAIL + collect assets",
        "next_action_date": datetime.now().strftime("%Y-%m-%d"),
    }
    update_cells(worksheet, row_idx, sheet_updates)

    return actions


def process_website_creating(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """
    Process a 'website_creating' lead: this means they chose a design and provided assets.
    Build final website, deploy, generate delivery + invoice emails.
    """
    actions = []
    biz = lead["business_name"]
    lead_id = lead["lead_id"]
    row_idx = lead["_row_idx"]
    city = lead.get("city", "")
    owner_name = lead.get("owner_name", "").strip()
    owner_email = lead.get("owner_email", "").strip()
    chosen = lead.get("chosen_template", "").strip()

    if not chosen:
        actions.append({
            "type": "WARNING",
            "priority": "MEDIUM",
            "business": biz,
            "message": f"{biz}: Status is 'website_creating' but no chosen_template set. Update the sheet with 1, 2, or 3.",
        })
        return actions

    print(f"\n  Processing WEBSITE_CREATING: {biz} (template {chosen})")

    # Generate delivery email
    delivery_gen = EMAIL_GENERATORS["delivery"]
    website_url = lead.get("website_url", "").strip()
    delivery_email = delivery_gen(
        business_name=biz, owner_name=owner_name, city=city,
        sender_name=sender_info["name"],
        sender_phone=sender_info["phone"],
        sender_email=sender_info["email"],
        context="",
        website_url=website_url,
    )
    delivery_path = save_intermediate({"email": delivery_email}, f"delivery_email_{lead_id}")

    actions.append({
        "type": "SEND_EMAIL",
        "priority": "HIGH",
        "business": biz,
        "to": owner_email,
        "subject": delivery_email["subject"],
        "file": delivery_path,
        "message": f"Send delivery email to {owner_email} with website URL — {delivery_path}",
    })

    # Generate invoice email
    invoice_gen = EMAIL_GENERATORS["invoice"]
    invoice_email = invoice_gen(
        business_name=biz, owner_name=owner_name, city=city,
        sender_name=sender_info["name"],
        sender_phone=sender_info["phone"],
        sender_email=sender_info["email"],
        context="",
    )
    invoice_path = save_intermediate({"email": invoice_email}, f"invoice_email_{lead_id}")

    actions.append({
        "type": "SEND_EMAIL",
        "priority": "MEDIUM",
        "business": biz,
        "to": owner_email,
        "file": invoice_path,
        "message": f"Send invoice to {owner_email} — {invoice_path}",
    })

    # Domain purchase reminder
    domain_opts = [
        lead.get("domain_option_1", ""),
        lead.get("domain_option_2", ""),
        lead.get("domain_option_3", ""),
    ]
    domain_opts = [d for d in domain_opts if d]
    if domain_opts:
        actions.append({
            "type": "BUY_DOMAIN",
            "priority": "HIGH",
            "business": biz,
            "message": f"Buy domain for {biz}. Options: {', '.join(domain_opts)}. Then set CNAME → pages.dev.",
        })

    # Update sheet
    sheet_updates = {
        "next_action": "SEND DELIVERY + INVOICE + BUY DOMAIN",
        "next_action_date": datetime.now().strftime("%Y-%m-%d"),
    }
    update_cells(worksheet, row_idx, sheet_updates)

    return actions


# --- Processors map ---

PROCESSORS = {
    "new": process_new,
    "website_created": process_website_created,
    "whatsapp_sent": process_whatsapp_sent,
    "email_sent": process_email_sent,
    "responded": process_responded,
    "website_creating": process_website_creating,
}


def process_lead(lead: dict, worksheet, sender_info: dict) -> list[dict]:
    """Process a single lead through its next step. Returns action items."""
    status = lead.get("status", "").strip().lower()

    if status in ("sold", "rejected", ""):
        return []

    processor = PROCESSORS.get(status)
    if processor:
        try:
            return processor(lead, worksheet, sender_info)
        except Exception as e:
            return [{
                "type": "ERROR",
                "priority": "HIGH",
                "business": lead.get("business_name", "?"),
                "message": f"Error processing {lead.get('business_name', '?')}: {e}",
            }]
    else:
        return [{
            "type": "WARNING",
            "priority": "LOW",
            "business": lead.get("business_name", "?"),
            "message": f"Unknown status '{status}' for {lead.get('business_name', '?')}. Valid: new, website_created, email_sent, responded, website_creating, sold, rejected.",
        }]


# --- Actions: report, process, process-one ---

def action_report(worksheet, sheet_title: str) -> dict:
    """Generate a pipeline status report with action items."""
    leads = read_all_leads(worksheet)

    if not leads:
        print("\n  No leads found in sheet.")
        return {"leads": 0, "actions": []}

    # Count by status
    status_counts = Counter()
    for lead in leads:
        status = lead.get("status", "").strip().lower() or "(empty)"
        status_counts[status] += 1

    # Generate action items
    actions = []
    for lead in leads:
        status = lead.get("status", "").strip().lower()
        biz = lead.get("business_name", "?")
        owner_email = lead.get("owner_email", "").strip()
        phone = lead.get("phone", "")
        email_date_str = lead.get("email_sent_date", "").strip()
        next_action = lead.get("next_action", "").strip()

        if status == "new":
            actions.append({
                "type": "BUILD",
                "priority": "MEDIUM",
                "business": biz,
                "message": f"BUILD + DEPLOY: {biz} — ready for 3 draft websites",
            })

        elif status == "website_created":
            actions.append({
                "type": "SEND_WHATSAPP",
                "priority": "HIGH",
                "business": biz,
                "message": f"WHATSAPP SENDEN: {biz} — send WhatsApp to {phone}",
            })

        elif status == "whatsapp_sent":
            wa_date_str = lead.get("whatsapp_sent_date", "").strip()
            if wa_date_str:
                try:
                    wa_date = datetime.strptime(wa_date_str, "%Y-%m-%d")
                    days = (datetime.now() - wa_date).days
                    if days >= 7 and owner_email:
                        actions.append({
                            "type": "SEND_EMAIL",
                            "priority": "HIGH",
                            "business": biz,
                            "message": f"EMAIL FOLLOW-UP: {biz} — {days} days since WhatsApp, send email to {owner_email}",
                        })
                    elif days >= 3:
                        actions.append({
                            "type": "CALL",
                            "priority": "HIGH",
                            "business": biz,
                            "message": f"ANRUFEN: {biz} — {days} Tage seit WhatsApp, anrufen: {phone}",
                        })
                    else:
                        actions.append({
                            "type": "WAIT",
                            "priority": "LOW",
                            "business": biz,
                            "message": f"WARTEN: {biz} — WhatsApp vor {days} Tag(en), Anruf ab Tag 3",
                        })
                except ValueError:
                    pass

        elif status == "email_sent" and email_date_str:
            try:
                email_date = datetime.strptime(email_date_str, "%Y-%m-%d")
                days = (datetime.now() - email_date).days
                if days >= 14:
                    actions.append({
                        "type": "SEND_EMAIL",
                        "priority": "MEDIUM",
                        "business": biz,
                        "message": f"BREAKUP EMAIL: {biz} — {days} days since email, send Day 14 breakup",
                    })
                elif days >= 7:
                    actions.append({
                        "type": "SEND_EMAIL",
                        "priority": "HIGH",
                        "business": biz,
                        "message": f"FOLLOW-UP EMAIL: {biz} — {days} days, send Day 7 follow-up",
                    })
                elif days >= 3:
                    actions.append({
                        "type": "CALL",
                        "priority": "HIGH",
                        "business": biz,
                        "message": f"CALL FOLLOW-UP: {biz} — {days} days since email, call {phone}",
                    })
                else:
                    actions.append({
                        "type": "WAIT",
                        "priority": "LOW",
                        "business": biz,
                        "message": f"WAIT: {biz} — email sent {days} day(s) ago, follow-up due Day 3",
                    })
            except ValueError:
                pass

        elif status == "responded":
            actions.append({
                "type": "ONBOARDING",
                "priority": "HIGH",
                "business": biz,
                "message": f"ONBOARDING: {biz} — collect design choice, values, logo, images",
            })

        elif status == "website_creating":
            actions.append({
                "type": "BUILD_FINAL",
                "priority": "HIGH",
                "business": biz,
                "message": f"BUILD FINAL: {biz} — build final site, deploy, send delivery + invoice",
            })

    # Sort actions by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    actions.sort(key=lambda a: priority_order.get(a.get("priority", "LOW"), 3))

    # Print report
    print(f"\n{'='*60}")
    print(f"  Pipeline Status Report")
    print(f"  Sheet: {sheet_title}")
    print(f"  Total leads: {len(leads)}")
    print(f"{'='*60}")

    # Status summary
    status_order = ["new", "website_created", "whatsapp_sent", "email_sent", "responded",
                    "website_creating", "sold", "rejected", "closed_no_response", "(empty)"]
    for s in status_order:
        if s in status_counts:
            hint = {
                "new": "BUILD + DEPLOY ready",
                "website_created": "WHATSAPP senden",
                "whatsapp_sent": "check follow-up timing (call Day 3, email Day 7)",
                "email_sent": "check follow-up timing",
                "responded": "ONBOARDING needed",
                "website_creating": "BUILD FINAL ready",
                "sold": "complete",
                "rejected": "complete",
                "(empty)": "no status set",
            }.get(s, "")
            print(f"  {s:25s}  {status_counts[s]:3d} leads  {f'  {hint}' if hint else ''}")

    # Action items
    if actions:
        high_actions = [a for a in actions if a.get("priority") == "HIGH"]
        med_actions = [a for a in actions if a.get("priority") == "MEDIUM"]
        low_actions = [a for a in actions if a.get("priority") == "LOW"]

        print(f"\n{'='*60}")
        print(f"  Action Items For You")
        print(f"{'='*60}")

        if high_actions:
            print(f"\n  Priority: HIGH")
            for i, a in enumerate(high_actions, 1):
                print(f"  {i}. {a['message']}")

        if med_actions:
            print(f"\n  Priority: MEDIUM")
            for i, a in enumerate(med_actions, 1):
                print(f"  {i}. {a['message']}")

        if low_actions:
            print(f"\n  Priority: LOW")
            for i, a in enumerate(low_actions, 1):
                print(f"  {i}. {a['message']}")
    else:
        print(f"\n  No action items — all leads are complete or waiting.")

    # === Operational Summary: What You Need To Buy / Do ===
    paid_no_domain = [
        l for l in leads
        if l.get("status", "").strip().lower() in ("sold", "website_creating")
        and not l.get("custom_domain", "").strip()
    ]
    unanswered = [
        l for l in leads
        if l.get("status", "").strip().lower() == "email_sent"
    ]
    emails_out_total = len([
        l for l in leads
        if l.get("email_sent_date", "").strip()
    ])
    responded_leads = [
        l for l in leads
        if l.get("status", "").strip().lower() == "responded"
    ]
    sold_leads = [
        l for l in leads
        if l.get("status", "").strip().lower() == "sold"
    ]

    print(f"\n{'='*60}")
    print(f"  Operational Summary")
    print(f"{'='*60}")
    print(f"  Cold emails sent (total):     {emails_out_total}")
    print(f"  Awaiting response:            {len(unanswered)}")
    print(f"  Responded (need onboarding):  {len(responded_leads)}")
    print(f"  Sold / active customers:      {len(sold_leads)}")

    if paid_no_domain:
        print(f"\n  *** DOMAINS TO BUY ({len(paid_no_domain)}): ***")
        for l in paid_no_domain:
            biz = l.get("business_name", "?")
            suggested = l.get("suggested_domain", l.get("domain_1", "no domain suggested"))
            print(f"    - {biz}: buy {suggested}")

    if responded_leads:
        print(f"\n  *** NEEDS YOUR ATTENTION ({len(responded_leads)}): ***")
        for l in responded_leads:
            biz = l.get("business_name", "?")
            print(f"    - {biz}: responded — start onboarding call")

    # Conversion funnel
    total = len(leads)
    if total > 0:
        print(f"\n  Conversion Funnel:")
        print(f"    Leads:           {total}")
        print(f"    Emails sent:     {emails_out_total}  ({emails_out_total*100//total}%)")
        print(f"    Responded:       {len(responded_leads)}  ({len(responded_leads)*100//max(emails_out_total,1)}% of emails)")
        print(f"    Sold:            {len(sold_leads)}  ({len(sold_leads)*100//max(len(responded_leads),1)}% of responded)")

    print(f"\n{'='*60}")

    return {
        "total_leads": len(leads),
        "status_counts": dict(status_counts),
        "actions": actions,
        "emails_out": emails_out_total,
        "unanswered": len(unanswered),
        "responded": len(responded_leads),
        "sold": len(sold_leads),
        "domains_to_buy": [l.get("business_name", "?") for l in paid_no_domain],
    }


def action_process(worksheet, sender_info: dict, sheet_title: str) -> dict:
    """Process ALL leads through their next automated step."""
    leads = read_all_leads(worksheet)

    if not leads:
        print("\n  No leads found in sheet.")
        return {"processed": 0, "actions": []}

    print(f"\n{'='*60}")
    print(f"  Processing All Leads")
    print(f"  Sheet: {sheet_title}")
    print(f"  Total leads: {len(leads)}")
    print(f"{'='*60}")

    all_actions = []
    processed = 0

    for lead in leads:
        status = lead.get("status", "").strip().lower()
        if status in ("sold", "rejected", ""):
            continue

        actions = process_lead(lead, worksheet, sender_info)
        all_actions.extend(actions)
        if actions:
            processed += 1

    # Print summary
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_actions.sort(key=lambda a: priority_order.get(a.get("priority", "LOW"), 3))

    print(f"\n{'='*60}")
    print(f"  Processing Complete")
    print(f"{'='*60}")
    print(f"  Leads processed: {processed}")
    print(f"  Action items generated: {len(all_actions)}")

    if all_actions:
        print(f"\n{'='*60}")
        print(f"  What You Need To Do")
        print(f"{'='*60}")
        for i, a in enumerate(all_actions, 1):
            priority = a.get("priority", "")
            print(f"  {i}. [{priority}] {a['message']}")

    return {
        "processed": processed,
        "actions": all_actions,
    }


def action_process_one(worksheet, lead_id: str, sender_info: dict) -> dict:
    """Process a single lead by its lead_id."""
    leads = read_all_leads(worksheet)

    target = None
    for lead in leads:
        if lead.get("lead_id") == lead_id:
            target = lead
            break

    if target is None:
        print(f"\n  ERROR: Lead ID '{lead_id}' not found in sheet.")
        return {"found": False, "actions": []}

    biz = target.get("business_name", "?")
    status = target.get("status", "").strip().lower()
    print(f"\n  Processing: {biz} (status: {status})")

    actions = process_lead(target, worksheet, sender_info)

    if actions:
        print(f"\n{'='*60}")
        print(f"  What You Need To Do")
        print(f"{'='*60}")
        for i, a in enumerate(actions, 1):
            priority = a.get("priority", "")
            print(f"  {i}. [{priority}] {a['message']}")
    else:
        print(f"\n  No actions needed for {biz} (status: {status})")

    return {"found": True, "lead_id": lead_id, "business": biz, "actions": actions}


def action_send_emails(worksheet, sender_info: dict, sheet_title: str, count: int) -> dict:
    """Send cold emails to leads with deployed websites. Auto-processes new leads if needed."""
    leads = read_all_leads(worksheet)

    if not leads:
        print("\n  No leads found in sheet.")
        return {"sent": 0, "processed_new": 0, "errors": []}

    # Step 1: Find leads ready for email (website_created + has email + has draft URLs)
    ready_leads = [
        l for l in leads
        if l.get("status", "").strip().lower() == "website_created"
        and l.get("owner_email", "").strip()
        and any(l.get(f"draft_url_{i}", "") for i in range(1, 5))
    ]

    # Step 2: If not enough, find 'new' leads we can process first
    new_leads = [
        l for l in leads
        if l.get("status", "").strip().lower() == "new"
        and l.get("owner_email", "").strip()
    ]

    available = len(ready_leads)
    need_more = max(0, count - available)
    new_to_process = new_leads[:need_more] if need_more > 0 else []

    print(f"\n{'='*60}")
    print(f"  Send Cold Emails")
    print(f"  Sheet: {sheet_title}")
    print(f"  Requested: {count}")
    print(f"  Ready to send: {available}")
    if new_to_process:
        print(f"  New leads to process first: {len(new_to_process)}")
    print(f"{'='*60}")

    # Step 3: Process new leads first (build + deploy websites)
    processed_new = 0
    for lead in new_to_process:
        biz = lead.get("business_name", "?")
        print(f"\n  Processing NEW lead: {biz}...")
        try:
            process_new(lead, worksheet, sender_info)
            processed_new += 1
        except Exception as e:
            print(f"  ERROR processing {biz}: {e}")

    # Re-read all leads after processing new ones
    if processed_new > 0:
        leads = read_all_leads(worksheet)
        ready_leads = [
            l for l in leads
            if l.get("status", "").strip().lower() == "website_created"
            and l.get("owner_email", "").strip()
            and any(l.get(f"draft_url_{i}", "") for i in range(1, 5))
        ]

    # Step 4: Send emails
    sent = 0
    errors = []
    send_list = ready_leads[:count]

    print(f"\n  Sending {len(send_list)} emails...")

    for lead in send_list:
        biz = lead.get("business_name", "?")
        lead_id = lead.get("lead_id", "")
        owner_email = lead.get("owner_email", "").strip()
        owner_name = lead.get("owner_name", "").strip()
        row_idx = lead["_row_idx"]

        url1 = lead.get("draft_url_1", "")
        url2 = lead.get("draft_url_2", "")
        url3 = lead.get("draft_url_3", "")
        url4 = lead.get("draft_url_4", "") or url3 or url2 or url1

        if not any([url1, url2, url3, url4]):
            errors.append(f"{biz}: No draft URLs")
            continue

        try:
            # Generate email
            ss1 = get_screenshot_url(url1)
            ss2 = get_screenshot_url(url2)
            ss3 = get_screenshot_url(url3)
            ss4 = get_screenshot_url(url4)

            email = generate_day0_email(
                business_name=biz,
                owner_name=owner_name,
                url1=url1, url2=url2, url3=url3, url4=url4,
                ss1=ss1, ss2=ss2, ss3=ss3, ss4=ss4,
                lead_id=lead_id,
                sender_name=sender_info["name"],
                sender_phone=sender_info["phone"],
                sender_email=sender_info["email"],
            )

            # Capture screenshots for inline images
            print(f"  [{sent+1}/{len(send_list)}] {biz} -> {owner_email}")
            screenshot_urls = [url1, url2, url3, url4]
            cids = ["ss1", "ss2", "ss3", "ss4"]
            inline_images = []
            for url, cid in zip(screenshot_urls, cids):
                if url:
                    try:
                        png_bytes = capture_screenshot_bytes(url)
                        inline_images.append((png_bytes, cid))
                    except Exception as e:
                        print(f"    Warning: Screenshot failed for {url}: {e}")

            # Send via SMTP
            send_email(
                to_email=owner_email,
                subject=email["subject"],
                body_text=email["body"],
                body_html=email["body_html"],
                from_name=sender_info["name"],
                from_email=sender_info["email"],
                inline_images=inline_images,
            )

            # Update sheet
            update_cells(worksheet, row_idx, {
                "status": "email_sent",
                "email_sent_date": datetime.now().strftime("%Y-%m-%d"),
                "next_action": "WAIT FOR RESPONSE",
                "next_action_date": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
            })

            # Save email to .tmp for records
            email_result = {
                "generated_at": datetime.now().isoformat(),
                "sent": True,
                "recipient": {"business_name": biz, "owner_email": owner_email},
                "emails": [email],
            }
            save_intermediate(email_result, f"sent_email_{lead_id}")

            sent += 1
            print(f"    Sent + sheet updated")

        except Exception as e:
            errors.append(f"{biz}: {e}")
            print(f"    ERROR: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Send Emails Complete")
    print(f"{'='*60}")
    print(f"  Sent: {sent}/{count} requested")
    if processed_new:
        print(f"  New leads processed: {processed_new}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for err in errors:
            print(f"    - {err}")

    remaining = len([
        l for l in leads
        if l.get("status", "").strip().lower() in ("new", "website_created")
        and l.get("owner_email", "").strip()
    ]) - sent
    print(f"  Leads remaining (new + website_created with email): {max(0, remaining)}")

    return {
        "sent": sent,
        "processed_new": processed_new,
        "errors": errors,
        "requested": count,
    }


def action_send_whatsapp(worksheet, sender_info: dict, sheet_title: str, count: int) -> dict:
    """Generate WhatsApp wa.me links for leads with deployed websites."""
    leads = read_all_leads(worksheet)

    if not leads:
        print("\n  No leads found in sheet.")
        return {"generated": 0, "errors": []}

    # Find leads ready for WhatsApp (website_created + has phone + has draft URLs)
    ready_leads = [
        l for l in leads
        if l.get("status", "").strip().lower() == "website_created"
        and l.get("phone", "").strip()
        and any(l.get(f"draft_url_{i}", "") for i in range(1, 5))
    ]

    print(f"\n{'='*60}")
    print(f"  Send WhatsApp Messages")
    print(f"  Sheet: {sheet_title}")
    print(f"  Ready to send: {len(ready_leads)}")
    print(f"  Requested: {count}")
    print(f"{'='*60}")

    if not ready_leads:
        print("\n  No leads ready for WhatsApp. Build websites first (status=new → process).")
        return {"generated": 0, "errors": []}

    generated = 0
    errors = []
    wa_links = []
    send_list = ready_leads[:count]

    for lead in send_list:
        biz = lead.get("business_name", "?")
        phone = lead.get("phone", "")
        row_idx = lead["_row_idx"]

        wa_result = generate_whatsapp_for_lead(lead, sender_info["name"], variant="day0")

        if "error" in wa_result:
            errors.append(f"{biz}: {wa_result['error']}")
            print(f"  ERROR: {biz} — {wa_result['error']}")
            continue

        wa_links.append(wa_result)
        generated += 1

        # Update sheet
        update_cells(worksheet, row_idx, {
            "status": "whatsapp_sent",
            "whatsapp_sent_date": datetime.now().strftime("%Y-%m-%d"),
            "whatsapp_status": "wa_sent",
            "next_action": "ANRUFEN (Tag 3)",
            "next_action_date": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
        })

    # Print all wa.me links for clicking
    if wa_links:
        print(f"\n{'='*60}")
        print(f"  Klicken Sie jeden Link — WhatsApp öffnet sich:")
        print(f"{'='*60}")
        for i, wa in enumerate(wa_links, 1):
            print(f"\n  {i}. {wa['business_name']} ({wa['phone']})")
            print(f"     {wa['wa_me_link']}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  WhatsApp Complete")
    print(f"{'='*60}")
    print(f"  Generated: {generated}/{count} requested")
    if errors:
        print(f"  Errors: {len(errors)}")
        for err in errors:
            print(f"    - {err}")

    remaining = len([
        l for l in leads
        if l.get("status", "").strip().lower() in ("new", "website_created")
        and l.get("phone", "").strip()
    ]) - generated
    print(f"  Leads remaining: {max(0, remaining)}")

    return {
        "generated": generated,
        "wa_links": [{"business": w["business_name"], "link": w["wa_me_link"]} for w in wa_links],
        "errors": errors,
        "requested": count,
    }


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Pipeline Manager — Orchestrate the Website Builder pipeline")
    parser.add_argument("--sheet-url", help="Google Sheet URL with leads (default: LEADS_SHEET_URL from .env)")
    parser.add_argument("--action", choices=["report", "process", "process-one", "send-emails", "send-whatsapp"],
                        help="Action to perform")
    parser.add_argument("--find-lead", metavar="NAME", help="Fuzzy-search for a lead by business name")
    parser.add_argument("--lead-id", help="Lead ID (required for process-one)")
    parser.add_argument("--sender-name", help="Your name (required for process/process-one)")
    parser.add_argument("--sender-phone", help="Your phone (required for process/process-one)")
    parser.add_argument("--sender-email", help="Your email (required for process/process-one/send-emails)")
    parser.add_argument("--count", type=int, default=10, help="Number of emails to send (for send-emails action)")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format: text (verbose) or json (compact)")
    args = parser.parse_args()

    if not args.action and not args.find_lead:
        parser.error("Either --action or --find-lead is required")

    # Resolve sheet URL: explicit arg > .env canonical > error
    sheet_url = args.sheet_url or CANONICAL_SHEET_URL
    if not sheet_url:
        parser.error("No sheet URL provided. Either pass --sheet-url or set LEADS_SHEET_URL in .env")
    if not args.sheet_url and CANONICAL_SHEET_URL:
        print(f"Using canonical sheet from .env: {CANONICAL_SHEET_URL}")

    # Validate args — fall back to .env values if CLI args not provided
    if args.action in ("process", "process-one", "send-emails", "send-whatsapp"):
        args.sender_name = args.sender_name or os.getenv("SENDER_NAME", "")
        args.sender_phone = args.sender_phone or os.getenv("SENDER_PHONE", "")
        args.sender_email = args.sender_email or os.getenv("SENDER_EMAIL", "")
        if not all([args.sender_name, args.sender_email]):
            parser.error("--sender-name and --sender-email are required (pass via CLI or set SENDER_NAME/SENDER_EMAIL in .env)")

    if args.action == "process-one" and not args.lead_id:
        parser.error("--lead-id is required for process-one")

    sender_info = {
        "name": args.sender_name or "",
        "phone": args.sender_phone or "",
        "email": args.sender_email or "",
    }

    # Open sheet
    if args.format == "text":
        print(f"\nOpening Google Sheet...")
    spreadsheet, worksheet = open_sheet(sheet_url)
    sheet_title = spreadsheet.title
    if args.format == "text":
        print(f"  Sheet: {sheet_title}")

    # Handle --find-lead
    if args.find_lead:
        matches = find_lead_by_name(worksheet, args.find_lead)
        if args.format == "json":
            print(json.dumps({"query": args.find_lead, "matches": matches}, indent=2, ensure_ascii=False))
        else:
            if matches:
                print(f"\n  Found {len(matches)} match(es) for '{args.find_lead}':")
                for m in matches:
                    print(f"    {m['business_name']} ({m['city']}) — ID: {m['lead_id']}, status: {m['status']}, score: {m['match_score']}")
            else:
                print(f"\n  No matches found for '{args.find_lead}'")
        return

    # Execute action
    if args.action == "report":
        result = action_report(worksheet, sheet_title)
    elif args.action == "process":
        result = action_process(worksheet, sender_info, sheet_title)
    elif args.action == "send-emails":
        result = action_send_emails(worksheet, sender_info, sheet_title, args.count)
    elif args.action == "send-whatsapp":
        result = action_send_whatsapp(worksheet, sender_info, sheet_title, args.count)
    elif args.action == "process-one":
        result = action_process_one(worksheet, args.lead_id, sender_info)

    # Output
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # Save result
    action_name = args.action or "find-lead"
    output_path = save_intermediate(result, f"pipeline_{action_name}")
    if args.format == "text":
        print(f"\n  Report saved to: {output_path}")


if __name__ == "__main__":
    main()
