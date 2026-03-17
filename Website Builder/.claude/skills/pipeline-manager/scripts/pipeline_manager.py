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
import importlib.util
import json
import os
import subprocess
import sys
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
)

# Call assistant
sys.path.insert(0, str(SKILLS_DIR / "call-assistant" / "scripts"))
from generate_call_script import generate_call_script

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
    "domain_option_2": 23,
    "domain_option_3": 24,
    "website_url": 25,
    "email_sent_date": 26,
    "response_date": 27,
    "notes": 28,
    "draft_url_1": 29,
    "draft_url_2": 30,
    "draft_url_3": 31,
    "draft_url_4": 32,
    "chosen_template": 33,
    "next_action": 34,
    "next_action_date": 35,
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

    for template_name in template_order:
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

    # Step 4: Generate outreach
    owner_email = lead.get("owner_email", "").strip()
    owner_name = lead.get("owner_name", "").strip()

    # Get the 3 URLs in order for email/call script
    url_list = [draft_urls.get(t, "") for t in template_order]
    url1 = url_list[0] if len(url_list) > 0 else ""
    url2 = url_list[1] if len(url_list) > 1 else ""
    url3 = url_list[2] if len(url_list) > 2 else ""
    url4 = url_list[3] if len(url_list) > 3 else ""
    if not url4:
        url4 = url3 or url2 or url1

    if owner_email:
        # Generate cold email
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
        email_result = {
            "generated_at": datetime.now().isoformat(),
            "recipient": {"business_name": biz, "owner_email": owner_email},
            "emails": [email],
        }
        email_path = save_intermediate(email_result, f"cold_email_{lead_id}")
        sheet_updates["next_action"] = f"SEND EMAIL to {owner_email}"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "SEND_EMAIL",
            "priority": "HIGH",
            "business": biz,
            "to": owner_email,
            "subject": email["subject"],
            "file": email_path,
            "message": f"Send cold email to {owner_email} — copy from {email_path}",
        })
    else:
        # Generate call script
        phone = lead.get("phone", "")
        script = generate_call_script(
            business_name=biz,
            category=category,
            city=city,
            phone=phone,
            owner_name=owner_name,
            url1=url1, url2=url2, url3=url3,
            sender_name=sender_info["name"],
            email_sent=False,
        )
        script_path = save_intermediate(script, f"call_script_{lead_id}")
        sheet_updates["next_action"] = f"CALL {phone}"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "CALL",
            "priority": "HIGH",
            "business": biz,
            "phone": phone,
            "file": script_path,
            "message": f"No email found. Call {biz} at {phone} — script at {script_path}",
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

    sheet_updates = {}

    if owner_email:
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
        email_result = {
            "generated_at": datetime.now().isoformat(),
            "recipient": {"business_name": biz, "owner_email": owner_email},
            "emails": [email],
        }
        email_path = save_intermediate(email_result, f"cold_email_{lead_id}")
        sheet_updates["status"] = "email_sent"
        sheet_updates["email_sent_date"] = datetime.now().strftime("%Y-%m-%d")
        sheet_updates["next_action"] = f"SEND EMAIL to {owner_email}"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "SEND_EMAIL",
            "priority": "HIGH",
            "business": biz,
            "to": owner_email,
            "subject": email["subject"],
            "file": email_path,
            "message": f"Send cold email to {owner_email} — copy from {email_path}",
        })
    else:
        phone = lead.get("phone", "")
        script = generate_call_script(
            business_name=biz, category=category, city=city,
            phone=phone, owner_name=owner_name,
            url1=url1, url2=url2, url3=url3,
            sender_name=sender_info["name"], email_sent=False,
        )
        script_path = save_intermediate(script, f"call_script_{lead_id}")
        sheet_updates["next_action"] = f"CALL {phone}"
        sheet_updates["next_action_date"] = datetime.now().strftime("%Y-%m-%d")

        actions.append({
            "type": "CALL",
            "priority": "HIGH",
            "business": biz,
            "phone": phone,
            "file": script_path,
            "message": f"No email found. Call {biz} at {phone} — script at {script_path}",
        })

    update_cells(worksheet, row_idx, sheet_updates)
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
            if owner_email:
                actions.append({
                    "type": "SEND_EMAIL",
                    "priority": "HIGH",
                    "business": biz,
                    "message": f"SEND EMAIL: {biz} — cold email to {owner_email}",
                })
            else:
                actions.append({
                    "type": "CALL",
                    "priority": "HIGH",
                    "business": biz,
                    "message": f"CALL: {biz} — no email, call {phone}",
                })

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
    status_order = ["new", "website_created", "email_sent", "responded",
                    "website_creating", "sold", "rejected", "(empty)"]
    for s in status_order:
        if s in status_counts:
            hint = {
                "new": "BUILD + DEPLOY ready",
                "website_created": "OUTREACH ready",
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

    return {
        "total_leads": len(leads),
        "status_counts": dict(status_counts),
        "actions": actions,
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


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Pipeline Manager — Orchestrate the Website Builder pipeline")
    parser.add_argument("--sheet-url", help="Google Sheet URL with leads (default: LEADS_SHEET_URL from .env)")
    parser.add_argument("--action", required=True, choices=["report", "process", "process-one"],
                        help="Action to perform")
    parser.add_argument("--lead-id", help="Lead ID (required for process-one)")
    parser.add_argument("--sender-name", help="Your name (required for process/process-one)")
    parser.add_argument("--sender-phone", help="Your phone (required for process/process-one)")
    parser.add_argument("--sender-email", help="Your email (required for process/process-one)")
    args = parser.parse_args()

    # Resolve sheet URL: explicit arg > .env canonical > error
    sheet_url = args.sheet_url or CANONICAL_SHEET_URL
    if not sheet_url:
        parser.error("No sheet URL provided. Either pass --sheet-url or set LEADS_SHEET_URL in .env")
    if not args.sheet_url and CANONICAL_SHEET_URL:
        print(f"Using canonical sheet from .env: {CANONICAL_SHEET_URL}")

    # Validate args
    if args.action in ("process", "process-one"):
        if not all([args.sender_name, args.sender_phone, args.sender_email]):
            parser.error("--sender-name, --sender-phone, and --sender-email are required for process/process-one")

    if args.action == "process-one" and not args.lead_id:
        parser.error("--lead-id is required for process-one")

    sender_info = {
        "name": args.sender_name or "",
        "phone": args.sender_phone or "",
        "email": args.sender_email or "",
    }

    # Open sheet
    print(f"\nOpening Google Sheet...")
    spreadsheet, worksheet = open_sheet(sheet_url)
    sheet_title = spreadsheet.title
    print(f"  Sheet: {sheet_title}")

    # Execute action
    if args.action == "report":
        result = action_report(worksheet, sheet_title)
    elif args.action == "process":
        result = action_process(worksheet, sender_info, sheet_title)
    elif args.action == "process-one":
        result = action_process_one(worksheet, args.lead_id, sender_info)

    # Save result
    output_path = save_intermediate(result, f"pipeline_{args.action}")
    print(f"\n  Report saved to: {output_path}")


if __name__ == "__main__":
    main()
