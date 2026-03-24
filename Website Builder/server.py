#!/usr/bin/env python3
"""
Dashboard API Server — Flask backend for the Website-Konfigurator.

Serves:
  - Static files (dashboard.html, .css, .js, landing page, etc.)
  - GET  /api/lead/<lead_id>        — Fetch lead data from Google Sheet
  - POST /api/lead/<lead_id>/order  — Submit order, upload files to Drive, update Sheet

Usage:
  cd "Website Builder"
  source .venv/bin/activate
  python3 server.py
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, send_file

import gspread

# --- Path setup (same pattern as pipeline_manager.py) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from execution.google_auth import get_credentials
from execution.copy_enrichment import enrich_template_copy
from execution.business_images import suggest_business_images
from execution.website_storage import get_order_output_dir

load_dotenv()

# --- Configuration ---
CANONICAL_SHEET_URL = os.getenv("LEADS_SHEET_URL", "")
DRIVE_UPLOAD_FOLDER_ID = os.getenv("DRIVE_UPLOAD_FOLDER_ID", "")

# --- Flask app ---
app = Flask(__name__, static_folder=".", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB max upload

# --- Temp file storage for preview uploads ---
TEMP_UPLOAD_DIR = os.path.join(PROJECT_ROOT, ".tmp", "preview_uploads")
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

# --- Column index map (1-indexed, matches Google Sheet schema) ---
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
}

COLUMN_NAMES = list(COL.keys())


# ============================================================
#  Sheet helpers (reused from pipeline_manager.py patterns)
# ============================================================

def open_sheet():
    """Open the canonical Google Sheet. Returns (spreadsheet, worksheet)."""
    if not CANONICAL_SHEET_URL:
        raise RuntimeError("LEADS_SHEET_URL not set in .env")

    creds = get_credentials()
    client = gspread.authorize(creds)

    if "/d/" in CANONICAL_SHEET_URL:
        sheet_id = CANONICAL_SHEET_URL.split("/d/")[1].split("/")[0]
    else:
        sheet_id = CANONICAL_SHEET_URL

    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet, spreadsheet.sheet1


def find_lead_by_id(worksheet, lead_id: str) -> dict | None:
    """Find a lead row by its lead_id. Returns dict with column data + _row_idx, or None."""
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1:
        return None

    for row_idx, row in enumerate(all_values[1:], start=2):
        if row[0].strip() == lead_id:
            lead = {}
            for i, col_name in enumerate(COLUMN_NAMES):
                lead[col_name] = row[i] if i < len(row) else ""
            lead["_row_idx"] = row_idx
            return lead

    return None


def update_cells(worksheet, row_idx: int, updates: dict):
    """Update multiple cells in a row by column name."""
    from gspread.utils import rowcol_to_a1

    cells = []
    for col_name, value in updates.items():
        if col_name not in COL:
            continue
        col_idx = COL[col_name]
        cell_ref = rowcol_to_a1(row_idx, col_idx)
        cells.append({"range": cell_ref, "values": [[str(value)]]})

    if cells:
        worksheet.batch_update(cells, value_input_option="USER_ENTERED")


# ============================================================
#  Google Drive helpers
# ============================================================

def get_drive_service():
    """Get Google Drive API v3 service."""
    from googleapiclient.discovery import build
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def get_or_create_lead_folder(drive_service, lead_id: str, business_name: str) -> str:
    """Get or create a Google Drive folder for this lead. Returns folder ID."""
    folder_name = f"{business_name} ({lead_id})"

    # Search for existing folder
    query = (
        f"name='{folder_name}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    if DRIVE_UPLOAD_FOLDER_ID:
        query += f" and '{DRIVE_UPLOAD_FOLDER_ID}' in parents"

    results = drive_service.files().list(
        q=query, spaces="drive", fields="files(id)"
    ).execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # Create new folder
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if DRIVE_UPLOAD_FOLDER_ID:
        metadata["parents"] = [DRIVE_UPLOAD_FOLDER_ID]

    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_file_to_drive(drive_service, folder_id: str, file_storage, filename: str) -> str:
    """Upload a file from Flask request.files to a Drive folder. Returns web view link."""
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(
        io.BytesIO(file_storage.read()),
        mimetype=file_storage.content_type or "application/octet-stream",
        resumable=True,
    )
    metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    uploaded = drive_service.files().create(
        body=metadata, media_body=media, fields="id,webViewLink"
    ).execute()
    return uploaded.get("webViewLink", "")


# ============================================================
#  API Endpoints
# ============================================================

@app.route("/api/lead/<lead_id>")
def get_lead(lead_id):
    """Fetch lead data for the dashboard."""
    # Validate 12-char hex format
    if not re.match(r"^[a-f0-9]{12}$", lead_id):
        return jsonify({"error": "Ungültiges Format. Prüfe die E-Mail mit deinem Code."}), 400

    try:
        _, worksheet = open_sheet()
        lead = find_lead_by_id(worksheet, lead_id)
    except Exception as e:
        print(f"Sheet error: {e}")
        return jsonify({"error": "Verbindungsfehler. Versuche es erneut."}), 500

    if not lead:
        return jsonify({"error": "Code nicht gefunden. Prüfe die E-Mail."}), 404

    # Build preview URLs (draft_url_1 through draft_url_4)
    # If draft URLs exist in the sheet, use those (deployed websites).
    # Otherwise, generate live preview URLs that serve templates with real data.
    template_keys = ["earlydog", "bia", "liveblocks", "loveseen"]
    previews = []
    for i in range(1, 5):
        url = lead.get(f"draft_url_{i}", "").strip()
        # Only use draft URL if it looks like a real URL (not a date or random text)
        if not url or not (url.startswith("http") or url.startswith("/")):
            url = f"/api/preview/{lead_id}/{template_keys[i - 1]}"
        previews.append(url)

    # Build domain suggestions from sheet or generate from business name
    business_name = lead.get("business_name", "")
    domains = []
    for i in range(1, 4):
        d = lead.get(f"domain_option_{i}", "").strip()
        if d:
            tld = "." + d.split(".")[-1] if "." in d else ".ch"
            purchase_url = lead.get(f"domain_option_{i}_purchase", "").strip()
            domains.append({"domain": d, "tld": tld, "available": True, "purchase_url": purchase_url})

    if not domains:
        # Generate from business name (same logic as old dashboard.js)
        clean = business_name.lower()
        for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("é", "e"), ("è", "e"), ("ê", "e")]:
            clean = clean.replace(old, new)
        clean = re.sub(r"[^a-z0-9]", "", clean)[:30]
        if not clean:
            clean = "meinbusiness"
        domains = [
            {"domain": f"{clean}.ch", "tld": ".ch", "available": True},
            {"domain": f"{clean}.com", "tld": ".com", "available": True},
            {"domain": f"{clean}-online.ch", "tld": ".ch", "available": True},
        ]

    # Set acquisition_source to "outreach" if not already set (code-based leads were contacted)
    if not lead.get("acquisition_source"):
        try:
            update_cells(worksheet, lead["_row_idx"], {"acquisition_source": "outreach"})
        except Exception as e:
            print(f"Source update error: {e}")

    return jsonify({
        "lead_id": lead_id,
        "business_name": business_name,
        "category": lead.get("category", ""),
        "city": lead.get("city", ""),
        "phone": lead.get("phone", ""),
        "owner_email": lead.get("owner_email", ""),
        "owner_name": lead.get("owner_name", ""),
        "address": lead.get("address", ""),
        "status": lead.get("status", ""),
        "previews": previews,
        "domains": domains,
        "chosen_template": lead.get("chosen_template", ""),
        "notes": lead.get("notes", ""),
    })


@app.route("/api/lead/register", methods=["POST"])
def register_lead():
    """Register a new lead from email (no-code flow)."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return jsonify({"error": "Bitte gib eine gültige E-Mail-Adresse ein."}), 400

    try:
        _, worksheet = open_sheet()
    except Exception as e:
        print(f"Sheet error: {e}")
        return jsonify({"error": "Verbindungsfehler."}), 500

    # Check if this email already has a lead (dedup)
    try:
        all_values = worksheet.get_all_values()
        email_col = COL["owner_email"] - 1
        for row_idx, row_data in enumerate(all_values[1:], start=2):
            if email_col < len(row_data) and row_data[email_col].strip().lower() == email:
                existing = {}
                for i, col_name in enumerate(COLUMN_NAMES):
                    existing[col_name] = row_data[i] if i < len(row_data) else ""
                print(f"[register] Existing lead for {email} → {existing['lead_id']}")
                template_keys = ["earlydog", "bia", "liveblocks", "loveseen"]
                return jsonify({
                    "lead_id": existing["lead_id"],
                    "business_name": existing.get("business_name", ""),
                    "category": existing.get("category", ""),
                    "city": existing.get("city", ""),
                    "phone": existing.get("phone", ""),
                    "owner_email": existing.get("owner_email", ""),
                    "owner_name": existing.get("owner_name", ""),
                    "address": existing.get("address", ""),
                    "status": existing.get("status", ""),
                    "previews": [f"/api/preview/{existing['lead_id']}/{t}" for t in template_keys],
                    "domains": [],
                    "chosen_template": existing.get("chosen_template", ""),
                    "notes": existing.get("notes", ""),
                })
    except Exception as e:
        print(f"Dedup check error: {e}")

    # Generate a 12-char hex lead_id
    import time
    raw = f"{email}{time.time()}".encode()
    lead_id = hashlib.sha256(raw).hexdigest()[:12]

    # Build row explicitly — only set known fields, everything else stays empty
    now = datetime.now().isoformat()
    row = []
    for col_name in COLUMN_NAMES:
        if col_name == "lead_id":
            row.append(lead_id)
        elif col_name == "scraped_at":
            row.append(now)
        elif col_name == "owner_email":
            row.append(email)
        elif col_name == "emails":
            row.append(email)
        elif col_name == "status":
            row.append("registered_no_code")
        elif col_name == "acquisition_source":
            row.append("organic")
        else:
            row.append("")

    print(f"[register] New lead: {lead_id} email: {email} row_len: {len(row)} non_empty: {sum(1 for v in row if v)}")

    try:
        worksheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"Append error: {e}")
        return jsonify({"error": "Registrierung fehlgeschlagen."}), 500

    template_keys = ["earlydog", "bia", "liveblocks", "loveseen"]
    return jsonify({
        "lead_id": lead_id,
        "business_name": "",
        "category": "",
        "city": "",
        "phone": "",
        "owner_email": email,
        "owner_name": "",
        "address": "",
        "status": "registered_no_code",
        "previews": [f"/api/preview/{lead_id}/{t}" for t in template_keys],
        "domains": [],
        "chosen_template": "",
        "notes": "",
    })


@app.route("/api/lead/<lead_id>/update", methods=["POST"])
def update_lead(lead_id):
    """Update lead data (no-code flow: add business name, description etc.)."""
    data = request.get_json(silent=True) or {}

    try:
        _, worksheet = open_sheet()
        lead = find_lead_by_id(worksheet, lead_id)
    except Exception as e:
        print(f"Sheet error: {e}")
        return jsonify({"error": "Verbindungsfehler."}), 500

    if not lead:
        return jsonify({"error": "Lead nicht gefunden."}), 404

    updates = {}
    if data.get("business_name"):
        updates["business_name"] = data["business_name"]
    if data.get("description") or data.get("values"):
        try:
            existing_notes = json.loads(lead.get("notes", "{}")) if lead.get("notes") else {}
        except (json.JSONDecodeError, TypeError):
            existing_notes = {}
        existing_notes["description"] = data.get("description", "")
        existing_notes["values"] = data.get("values", "")
        updates["notes"] = json.dumps(existing_notes, ensure_ascii=False)
    if data.get("category"):
        updates["category"] = data["category"]
    if data.get("city"):
        updates["city"] = data["city"]
    if data.get("phone"):
        updates["phone"] = data["phone"]
    if data.get("address"):
        updates["address"] = data["address"]
    if data.get("chosen_template"):
        updates["chosen_template"] = data["chosen_template"]
    if data.get("domain_option_1"):
        updates["domain_option_1"] = data["domain_option_1"]
    if data.get("domain_option_2"):
        updates["domain_option_2"] = data["domain_option_2"]
    if data.get("domain_option_3"):
        updates["domain_option_3"] = data["domain_option_3"]

    if updates:
        try:
            update_cells(worksheet, lead["_row_idx"], updates)
        except Exception as e:
            print(f"Update error: {e}")
            return jsonify({"error": "Update fehlgeschlagen."}), 500

    return jsonify({"success": True})


@app.route("/api/lead/<lead_id>/order", methods=["POST"])
def submit_order(lead_id):
    """Submit order: update sheet + upload files to Drive."""
    if not re.match(r"^[a-f0-9]{12}$", lead_id):
        return jsonify({"error": "Invalid lead ID format"}), 400

    try:
        _, worksheet = open_sheet()
        lead = find_lead_by_id(worksheet, lead_id)
    except Exception as e:
        print(f"Sheet error: {e}")
        return jsonify({"error": "Verbindungsfehler. Versuche es erneut."}), 500

    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    # Parse form data (multipart for file uploads)
    chosen_template = request.form.get("chosen_template", "")
    description = request.form.get("description", "")
    values = request.form.get("values", "")
    selected_domain = request.form.get("selected_domain", "")
    agreed_to_terms = request.form.get("agreed_to_terms", "false") == "true"

    if not agreed_to_terms:
        return jsonify({"error": "AGB müssen akzeptiert werden."}), 400

    if not chosen_template:
        return jsonify({"error": "Kein Template gewählt."}), 400

    # Upload files to Google Drive
    drive_folder_url = ""
    try:
        drive_service = get_drive_service()
        folder_id = get_or_create_lead_folder(
            drive_service, lead_id, lead.get("business_name", lead_id)
        )
        drive_folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

        # Upload logo
        if "logo" in request.files and request.files["logo"].filename:
            upload_file_to_drive(
                drive_service, folder_id,
                request.files["logo"],
                f"logo_{request.files['logo'].filename}",
            )

        # Upload images
        images = request.files.getlist("images")
        for img in images:
            if img.filename:
                upload_file_to_drive(
                    drive_service, folder_id, img,
                    f"image_{img.filename}",
                )
    except Exception as e:
        print(f"Drive upload error (non-fatal): {e}")
        # Continue — file upload failure shouldn't block the order

    # Build notes JSON with customization data
    notes_data = {
        "order_date": datetime.now().isoformat(),
        "description": description,
        "values": values,
        "selected_domain": selected_domain,
        "drive_folder": drive_folder_url,
    }
    notes_str = json.dumps(notes_data, ensure_ascii=False)

    # Update sheet
    row_idx = lead["_row_idx"]
    updates = {
        "chosen_template": chosen_template,
        "notes": notes_str,
        "status": "website_creating",
        "next_action": "BUILD FINAL WEBSITE",
        "next_action_date": datetime.now().strftime("%Y-%m-%d"),
    }
    if selected_domain:
        updates["domain_option_1"] = selected_domain

    try:
        update_cells(worksheet, row_idx, updates)
    except Exception as e:
        print(f"Sheet update error: {e}")
        return jsonify({"error": "Fehler beim Speichern. Versuche es erneut."}), 500

    # Build the static site now, while we still have the uploaded files in memory.
    # This captures exactly what was shown in the preview (same AI cache key).
    try:
        logo_f = request.files.get("logo")
        logo_bytes, logo_ext = None, None
        if logo_f and logo_f.filename:
            logo_f.stream.seek(0)
            logo_bytes = logo_f.read()
            logo_ext = os.path.splitext(logo_f.filename)[1] or ".png"

        image_data = []
        for img_f in request.files.getlist("images"):
            if img_f.filename:
                img_f.stream.seek(0)
                ext = os.path.splitext(img_f.filename)[1] or ".jpg"
                image_data.append((img_f.read(), ext))

        build_customizations = {"description": description, "values": values}
        _build_order_site(lead, chosen_template, build_customizations,
                          logo_bytes, logo_ext, image_data)
        print(f"[order] Site built for {lead_id}")
    except Exception as e:
        print(f"[order] Site build error (non-fatal): {e}")

    # Trigger post-order processing in the background (deploy + emails)
    _trigger_process_order(lead_id)

    return jsonify({
        "success": True,
        "message": "Bestellung erfolgreich!",
        "drive_folder": drive_folder_url,
    })


def _trigger_process_order(lead_id: str):
    """Fire-and-forget: run process_order.py in background after a confirmed order."""
    import threading

    script = os.path.join(
        PROJECT_ROOT,
        ".claude", "skills", "process-order", "scripts", "process_order.py",
    )
    if not os.path.exists(script):
        print(f"Warning: process_order.py not found at {script}")
        return

    def run():
        try:
            result = subprocess.run(
                [sys.executable, script, "--lead-id", lead_id],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=300,  # 5-minute max
            )
            if result.returncode != 0:
                print(f"[process-order] Error for {lead_id}:\n{result.stderr}")
            else:
                print(f"[process-order] Done for {lead_id}:\n{result.stdout[-500:]}")
        except Exception as e:
            print(f"[process-order] Exception for {lead_id}: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    print(f"[process-order] Background job started for {lead_id}")


# ============================================================
#  Template Preview — serve templates with real business data
# ============================================================

TEMPLATE_DIRS = {
    "earlydog": ".claude/skills/build-website-earlydog/template",
    "bia": ".claude/skills/build-website-bia/template",
    "liveblocks": ".claude/skills/build-website-liveblocks/template",
    "loveseen": ".claude/skills/build-website-loveseen/template",
}

# --- Skill module imports for website generation ---
SKILLS_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills")
sys.path.insert(0, os.path.join(SKILLS_DIR, "build-website-earlydog", "scripts"))
sys.path.insert(0, os.path.join(SKILLS_DIR, "build-website-bia", "scripts"))
sys.path.insert(0, os.path.join(SKILLS_DIR, "build-website-liveblocks", "scripts"))
sys.path.insert(0, os.path.join(SKILLS_DIR, "build-website-loveseen", "scripts"))

# Import each template's generate_website module
import importlib
_gen_modules = {}
for _tkey in ["earlydog", "bia", "liveblocks", "loveseen"]:
    _script = os.path.join(SKILLS_DIR, f"build-website-{_tkey}", "scripts", "generate_website.py")
    if os.path.exists(_script):
        _spec = importlib.util.spec_from_file_location(f"gen_{_tkey}", _script)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _gen_modules[_tkey] = _mod


def _lead_to_placeholder_data(lead: dict, customizations: dict = None) -> dict:
    """Map lead data from Google Sheets + anpassen step to placeholder dict.

    This dict is passed to merge_with_defaults() from the generate_website module,
    which fills in defaults, enriches copy, and fetches Pexels images.
    """
    cust = customizations or {}
    desc = cust.get("description", "")
    vals = cust.get("values", "")

    data = {
        "BUSINESS_NAME": lead.get("business_name", ""),
        "PHONE": lead.get("phone", ""),
        "EMAIL": lead.get("owner_email", "") or lead.get("emails", ""),
        "ADDRESS": lead.get("address", "") or lead.get("city", ""),
        "category": lead.get("category", ""),
        "city": lead.get("city", ""),
    }

    # Map description to relevant fields
    if desc:
        data["ABOUT_DESCRIPTION"] = desc
        data["HERO_DESCRIPTION"] = desc

    # Parse values into individual items for service/feature/value fields
    if vals:
        items = [v.strip() for v in re.split(r"[,\n;]+", vals) if v.strip()]
        for i, item in enumerate(items[:6]):
            data[f"SERVICE_{i+1}_TITLE"] = item
        if len(items) >= 2:
            data["STATEMENT_LINE1"] = items[0]
            data["STATEMENT_LINE2"] = items[1] if len(items) > 1 else ""
            data["STATEMENT_LINE3"] = items[2] if len(items) > 2 else ""

    # Remove empty values so defaults are used
    return {k: v for k, v in data.items() if v}


# Cache lead data briefly to avoid repeated sheet lookups for assets
_preview_lead_cache = {}

# Cache AI-generated content to avoid repeat API calls
_ai_content_cache = {}

# Template placeholder keys — used by AI generation prompt
TEMPLATE_PLACEHOLDERS = {
    "earlydog": [
        "BUSINESS_NAME", "TAGLINE", "META_DESCRIPTION", "HERO_TITLE_LINE1",
        "HERO_TITLE_LINE2", "HERO_DESCRIPTION", "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION",
        "SERVICE_1_CTA", "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION", "SERVICE_2_CTA",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICE_3_CTA", "CTA_TITLE_LINE1",
        "CTA_TITLE_LINE2", "PHONE", "EMAIL", "ADDRESS",
    ],
    "bia": [
        "BUSINESS_NAME", "BUSINESS_NAME_SHORT", "TAGLINE", "META_DESCRIPTION",
        "SECTION_LABEL_HERO", "HERO_TITLE_LINE1", "HERO_TITLE_LINE2", "HERO_TITLE_LINE3",
        "INTRO_TEXT", "INTRO_DESCRIPTION", "SECTION_LABEL_SERVICES", "SERVICES_HEADING",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION", "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICE_4_TITLE", "SERVICE_4_DESCRIPTION",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING", "ABOUT_DESCRIPTION",
        "STAT_1_NUMBER", "STAT_1_LABEL", "STAT_2_NUMBER", "STAT_2_LABEL",
        "STAT_3_NUMBER", "STAT_3_LABEL", "CTA_TITLE_LINE1", "CTA_TITLE_LINE2",
        "CTA_TITLE_LINE3", "PHONE", "EMAIL", "ADDRESS", "OPENING_HOURS",
    ],
    "liveblocks": [
        "BUSINESS_NAME", "BUSINESS_NAME_SHORT", "TAGLINE", "META_DESCRIPTION",
        "SECTION_LABEL_HERO", "HERO_TITLE_LINE1", "HERO_TITLE_LINE2",
        "HERO_WORD_1", "HERO_WORD_2", "HERO_WORD_3", "HERO_WORD_4",
        "HERO_DESCRIPTION", "CTA_BUTTON_PRIMARY", "CTA_BUTTON_SECONDARY",
        "TRUST_LABEL", "STAT_1_NUMBER", "STAT_1_LABEL", "STAT_2_NUMBER", "STAT_2_LABEL",
        "STAT_3_NUMBER", "STAT_3_LABEL", "STAT_4_NUMBER", "STAT_4_LABEL",
        "SECTION_LABEL_SERVICES", "SERVICES_HEADING", "SERVICES_DESCRIPTION",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION", "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICE_4_TITLE", "SERVICE_4_DESCRIPTION",
        "SERVICE_5_TITLE", "SERVICE_5_DESCRIPTION", "SERVICE_6_TITLE", "SERVICE_6_DESCRIPTION",
        "SECTION_LABEL_FEATURE", "FEATURE_HEADING", "FEATURE_DESCRIPTION",
        "FEATURE_POINT_1", "FEATURE_POINT_2", "FEATURE_POINT_3",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING", "ABOUT_LEAD", "ABOUT_DESCRIPTION",
        "VALUE_1_TITLE", "VALUE_1_DESCRIPTION", "VALUE_2_TITLE", "VALUE_2_DESCRIPTION",
        "VALUE_3_TITLE", "VALUE_3_DESCRIPTION", "CTA_HEADING_LINE1", "CTA_HEADING_LINE2",
        "CTA_DESCRIPTION", "CONTACT_CARD_1_TITLE", "CONTACT_CARD_1_DESCRIPTION",
        "CONTACT_CARD_2_TITLE", "CONTACT_CARD_2_DESCRIPTION",
        "PHONE", "PHONE_SHORT", "EMAIL", "ADDRESS", "OPENING_HOURS",
        "FOOTER_COL_1_TITLE", "FOOTER_COL_1_LINK_1", "FOOTER_COL_1_LINK_2",
        "FOOTER_COL_1_LINK_3", "FOOTER_COL_2_TITLE", "FOOTER_COL_2_LINK_1",
        "FOOTER_COL_2_LINK_2", "FOOTER_COL_2_LINK_3",
    ],
    "loveseen": [
        "BUSINESS_NAME", "TAGLINE", "META_DESCRIPTION", "NAV_CTA",
        "NAV_LINK_1", "NAV_LINK_2", "NAV_LINK_3", "NAV_LINK_4",
        "HERO_TITLE_LINE1", "HERO_TITLE_LINE2", "HERO_CTA",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING_LINE1", "ABOUT_HEADING_LINE2",
        "ABOUT_LEAD", "ABOUT_DESCRIPTION", "ABOUT_CTA",
        "STATEMENT_LABEL", "STATEMENT_LINE1", "STATEMENT_LINE2", "STATEMENT_LINE3",
        "SECTION_LABEL_SERVICES", "SERVICES_HEADING",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION", "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICES_CTA",
        "GALLERY_LABEL", "INSTAGRAM_HANDLE", "INSTAGRAM_URL",
        "CONTACT_TAGLINE", "EMAIL_PLACEHOLDER",
        "CONTACT_LABEL_PHONE", "CONTACT_LABEL_EMAIL", "CONTACT_LABEL_ADDRESS",
        "CONTACT_LABEL_HOURS", "PHONE", "EMAIL", "ADDRESS", "OPENING_HOURS",
        "FOOTER_PRIVACY", "FOOTER_TERMS", "FOOTER_YEAR",
    ],
}


TEMPLATE_IMAGE_SLOTS = {
    "earlydog": [
        {"slot": "hero", "file": "hero.svg", "desc": "Grosses Hero-Bild oben auf der Seite"},
        {"slot": "section1", "file": "section1.svg", "desc": "Service-Bereich 1"},
        {"slot": "section2", "file": "section2.svg", "desc": "Service-Bereich 2"},
        {"slot": "section3", "file": "section3.svg", "desc": "Service-Bereich 3"},
    ],
    "bia": [
        {"slot": "hero", "file": "hero.svg", "desc": "Grosses Hero-Bild oben auf der Seite"},
        {"slot": "showcase", "file": "showcase.svg", "desc": "Showcase/Portfolio-Bereich"},
        {"slot": "cta", "file": "cta.svg", "desc": "Call-to-Action-Bereich"},
        {"slot": "contact", "file": "contact.svg", "desc": "Kontakt-Bereich"},
    ],
    "liveblocks": [
        {"slot": "feature", "file": "feature.svg", "desc": "Feature/Highlight-Bereich"},
        {"slot": "about", "file": "about.svg", "desc": "Über-uns-Bereich"},
    ],
    "loveseen": [
        {"slot": "hero", "file": "hero.jpg", "desc": "Grosses Hero-Bild oben"},
        {"slot": "about", "file": "about.jpg", "desc": "Über-uns-Bereich"},
        {"slot": "gallery1", "file": "gallery1.jpg", "desc": "Galerie Hauptbild"},
        {"slot": "gallery2", "file": "gallery2.jpg", "desc": "Galerie klein 1"},
        {"slot": "gallery3", "file": "gallery3.jpg", "desc": "Galerie klein 2"},
    ],
}


def _generate_content_with_ai(lead: dict, template_key: str, customizations: dict) -> dict | None:
    """Generate tailored website content using Claude API.

    Returns a dict of placeholder→value, or None if API key is missing or call fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    # Check cache
    desc = customizations.get("description", "")
    vals = customizations.get("values", "")
    cache_key = f"{lead.get('lead_id', '')}:{template_key}:{hashlib.md5((desc + vals).encode()).hexdigest()}"
    if cache_key in _ai_content_cache:
        return _ai_content_cache[cache_key]

    placeholder_keys = TEMPLATE_PLACEHOLDERS.get(template_key, [])
    if not placeholder_keys:
        return None

    # Build the prompt
    biz = lead.get("business_name", "")
    category = lead.get("category", "")
    city = lead.get("city", "")
    phone = lead.get("phone", "")
    email = lead.get("owner_email", lead.get("emails", ""))
    address = lead.get("address", "")

    # Separate fixed values from AI-generated ones
    fixed_values = {
        "PHONE": phone or "Telefon",
        "PHONE_SHORT": phone[-13:] if len(phone) > 13 else phone or "Anrufen",
        "EMAIL": email or "info@example.ch",
        "ADDRESS": address or city or "Schweiz",
        "OPENING_HOURS": "Mo–Fr 08:00–18:00",
        "FOOTER_YEAR": "2026",
        "FOOTER_PRIVACY": "Datenschutz",
        "FOOTER_TERMS": "AGB",
        "EMAIL_PLACEHOLDER": "ihre@email.ch",
        "CONTACT_LABEL_PHONE": "Telefon",
        "CONTACT_LABEL_EMAIL": "E-Mail",
        "CONTACT_LABEL_ADDRESS": "Adresse",
        "CONTACT_LABEL_HOURS": "Öffnungszeiten",
        "INSTAGRAM_URL": "#",
    }

    # Keys that AI should generate
    ai_keys = [k for k in placeholder_keys if k not in fixed_values]

    system_prompt = (
        "Du bist ein professioneller Website-Texter für Schweizer KMUs. "
        "Du schreibst alle Texte auf Deutsch (Hochdeutsch, Schweiz-freundlich). "
        "Dein Stil: modern, professionell, prägnant. Website-Texte, keine Aufsätze. "
        "Hero-Titel: max 3-4 Wörter pro Zeile, wirkungsvoll wie eine Plakatwerbung. "
        "BUSINESS_NAME_SHORT: erstes aussagekräftiges Wort + Punkt (z.B. 'Weber.'). "
        "Stats: Zahlen im Format '15+', '500+', '100%'. "
        "Services: Konkret zur Branche, NICHT generisch ('Beratung', 'Umsetzung'). "
        "Antworte NUR mit einem JSON-Objekt. Keine Erklärungen."
    )

    user_prompt = (
        f"Geschäft: {biz}\n"
        f"Branche: {category}\n"
        f"Stadt: {city}\n"
        f"Kundenbeschreibung: {desc}\n"
        f"Werte/Besonderheiten: {vals}\n\n"
        f"Generiere ein JSON-Objekt mit diesen Schlüsseln:\n"
        f"{json.dumps(ai_keys, ensure_ascii=False)}\n\n"
        f"Jeder Wert ist ein String. Passe ALLE Texte an dieses spezifische Geschäft an."
    )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Parse JSON from response
        text = response.content[0].text.strip()
        # Handle possible markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        ai_values = json.loads(text)

        # Merge fixed + AI values
        result = {**fixed_values, **ai_values}

        # Cache the result
        _ai_content_cache[cache_key] = result
        return result

    except ImportError:
        print("WARNING: anthropic package not installed. Using fallback.")
        return None
    except Exception as e:
        print(f"AI content generation failed: {e}")
        return None


def _build_replacements(lead: dict, customizations: dict = None) -> dict:
    """Build a placeholder→value map from lead data + user customizations."""
    biz = lead.get("business_name", "Mein Business")
    city = lead.get("city", "")
    phone = lead.get("phone", "")
    email = lead.get("owner_email", lead.get("emails", ""))
    address = lead.get("address", "")
    category = lead.get("category", "")

    # User customizations from Step 3
    desc = (customizations or {}).get("description", "")
    values = (customizations or {}).get("values", "")

    # Short name: first word or up to first comma
    short = biz.split(",")[0].split(" ")[0] if biz else "Business"

    # Phone short (last 10 chars or full)
    phone_short = phone[-13:] if len(phone) > 13 else phone

    # Use user description for hero/about if provided
    hero_desc = desc if desc else f"Willkommen bei {biz}. Wir sind Ihr zuverlässiger Partner für {category.lower() or 'erstklassige Dienstleistungen'} in {city or 'Ihrer Region'}."
    about_desc = desc if desc else f"Mit Leidenschaft und Engagement sind wir Ihr zuverlässiger Partner in {city or 'der Schweiz'}."

    # Parse values/highlights into individual items
    value_items = [v.strip() for v in re.split(r"[,\n;]+", values) if v.strip()] if values else []

    replacements = {
        "BUSINESS_NAME": biz,
        "BUSINESS_NAME_SHORT": short,
        "TAGLINE": f"Ihr Partner in {city}" if city else "Ihr Partner für Qualität",
        "META_DESCRIPTION": f"{biz} — {category} in {city}" if city else biz,
        "HERO_TITLE_LINE1": biz.split(",")[0] if "," in biz else biz,
        "HERO_TITLE_LINE2": f"in {city}" if city else "Qualität & Vertrauen",
        "HERO_TITLE_LINE3": category or "Ihr Experte",
        "HERO_DESCRIPTION": hero_desc,
        "HERO_CTA": "Kontakt aufnehmen",
        "HERO_WORD_1": category or "Qualität",
        "PHONE": phone or "Telefon",
        "PHONE_SHORT": phone_short or "Anrufen",
        "EMAIL": email or "info@example.ch",
        "EMAIL_PLACEHOLDER": "ihre@email.ch",
        "ADDRESS": address or city or "Schweiz",
        "OPENING_HOURS": "Mo–Fr 08:00–18:00",
        "INSTAGRAM_HANDLE": "",
        "INSTAGRAM_URL": "#",
        "NAV_CTA": "Kontakt",
        "SECTION_LABEL_HERO": "Willkommen",
        "SECTION_LABEL_SERVICES": "Unsere Leistungen",
        "SECTION_LABEL_ABOUT": "Über uns",
        "SECTION_LABEL_FEATURE": "Warum wir",
        "TRUST_LABEL": f"Vertrauen Sie {short}",
        "STAT_1_NUMBER": value_items[0] if len(value_items) > 0 else "10+",
        "STAT_1_LABEL": value_items[1] if len(value_items) > 1 else "Jahre Erfahrung",
        "STAT_2_NUMBER": value_items[2] if len(value_items) > 2 else "500+",
        "STAT_2_LABEL": value_items[3] if len(value_items) > 3 else "Zufriedene Kunden",
        "STAT_3_NUMBER": "100%",
        "STAT_3_LABEL": "Engagement",
        "STAT_4_NUMBER": "24h",
        "STAT_4_LABEL": "Erreichbar",
        "SERVICES_HEADING": "Unsere Leistungen",
        "SERVICES_DESCRIPTION": f"Entdecken Sie unser Angebot bei {biz}.",
        "SERVICES_CTA": "Mehr erfahren",
        "SERVICE_1_TITLE": "Beratung",
        "SERVICE_1_DESCRIPTION": "Persönliche Beratung für Ihre Bedürfnisse.",
        "SERVICE_1_CTA": "Mehr erfahren →",
        "SERVICE_2_TITLE": "Umsetzung",
        "SERVICE_2_DESCRIPTION": "Professionelle Ausführung mit höchster Qualität.",
        "SERVICE_2_CTA": "Mehr erfahren →",
        "SERVICE_3_TITLE": "Nachbetreuung",
        "SERVICE_3_DESCRIPTION": "Langfristige Betreuung und Unterstützung.",
        "SERVICE_3_CTA": "Mehr erfahren →",
        "SERVICE_4_TITLE": "Planung",
        "SERVICE_4_DESCRIPTION": "Sorgfältige Planung für optimale Ergebnisse.",
        "SERVICE_5_TITLE": "Qualitätssicherung",
        "SERVICE_5_DESCRIPTION": "Höchste Standards bei jedem Projekt.",
        "SERVICE_6_TITLE": "Kundendienst",
        "SERVICE_6_DESCRIPTION": "Immer für Sie da — schnell und zuverlässig.",
        "FEATURE_HEADING": f"Warum {short}?",
        "FEATURE_DESCRIPTION": f"Wir stehen für Qualität, Zuverlässigkeit und Kundennähe in {city or 'der Schweiz'}.",
        "FEATURE_POINT_1": value_items[0] if len(value_items) > 0 else "Langjährige Erfahrung",
        "FEATURE_POINT_2": value_items[1] if len(value_items) > 1 else "Persönliche Betreuung",
        "FEATURE_POINT_3": value_items[2] if len(value_items) > 2 else "Faire Preise",
        "ABOUT_HEADING": f"Über {short}",
        "ABOUT_LEAD": f"{biz} steht für Qualität und Vertrauen.",
        "ABOUT_DESCRIPTION": about_desc,
        "ABOUT_CTA": "Mehr über uns",
        "VALUE_1_TITLE": value_items[0] if len(value_items) > 0 else "Qualität",
        "VALUE_1_DESCRIPTION": value_items[1] if len(value_items) > 1 else "Höchste Ansprüche an unsere Arbeit.",
        "VALUE_2_TITLE": value_items[2] if len(value_items) > 2 else "Vertrauen",
        "VALUE_2_DESCRIPTION": value_items[3] if len(value_items) > 3 else "Transparenz und Ehrlichkeit.",
        "VALUE_3_TITLE": value_items[4] if len(value_items) > 4 else "Innovation",
        "VALUE_3_DESCRIPTION": value_items[5] if len(value_items) > 5 else "Moderne Lösungen für Sie.",
        "CTA_TITLE_LINE1": "Bereit für",
        "CTA_TITLE_LINE2": "den nächsten Schritt?",
        "CTA_HEADING_LINE1": "Bereit für",
        "CTA_HEADING_LINE2": "den nächsten Schritt?",
        "CTA_DESCRIPTION": f"Kontaktieren Sie {biz} noch heute.",
        "CTA_BUTTON_PRIMARY": "Jetzt anrufen",
        "CTA_BUTTON_SECONDARY": "E-Mail senden",
        "CONTACT_TAGLINE": "Wir freuen uns auf Sie",
        "CONTACT_LABEL_PHONE": "Telefon",
        "CONTACT_LABEL_EMAIL": "E-Mail",
        "CONTACT_LABEL_ADDRESS": "Adresse",
        "CONTACT_LABEL_HOURS": "Öffnungszeiten",
        "INTRO_TEXT": f"Willkommen bei {biz}",
        "INTRO_DESCRIPTION": desc if desc else f"Ihr Partner für {category.lower() or 'Qualität'} in {city or 'der Schweiz'}.",
        "STATEMENT_LABEL": "Unser Versprechen",
        "GALLERY_LABEL": "Einblicke",
        "FOOTER_YEAR": "2026",
        "FOOTER_PRIVACY": "Datenschutz",
        "FOOTER_TERMS": "AGB",
    }

    return replacements


def _build_order_site(
    lead: dict,
    template_key: str,
    customizations: dict,
    logo_bytes: bytes | None,
    logo_ext: str | None,
    image_data: list,
) -> str:
    """Build the deployable static site using the new generation pipeline.

    Uses generate_website() from the skill scripts (enrichment + Pexels images),
    then overlays uploaded customer images and logo.
    Returns the path to the built site directory.
    """
    lead_id = lead.get("lead_id", "unknown")
    site_dir = os.path.join(PROJECT_ROOT, ".tmp", f"order_{lead_id}")

    gen_mod = _gen_modules.get(template_key)
    if not gen_mod:
        raise ValueError(f"No generation module for template: {template_key}")

    # Build placeholder data from lead + anpassen customizations
    placeholder_data = _lead_to_placeholder_data(lead, customizations)

    # If customer uploaded images, pass them as IMAGE_* overrides
    # Save image files first so we can reference them
    if image_data:
        assets_img_dir = os.path.join(site_dir, "assets", "images")
        os.makedirs(assets_img_dir, exist_ok=True)
        slot_map = getattr(gen_mod, "IMAGE_SLOT_MAP", {})
        image_keys = list(slot_map.keys())
        for i, (img_bytes, ext) in enumerate(image_data):
            if i < len(image_keys):
                filename = f"customer_img_{i + 1}{ext}"
                # We'll save these after generate_website copies the template
                # For now, just set the placeholder to the relative path
                placeholder_data[image_keys[i]] = f"assets/images/{filename}"

    # Generate website using the skill's pipeline
    # (enrichment + Pexels for unfilled IMAGE_* slots + template copy + fill)
    result = gen_mod.generate_website(placeholder_data, site_dir, overwrite=True)
    print(f"[build] Generated {template_key} for {lead_id}: {result.get('validation', {})}")

    # Now overlay uploaded customer images as real files
    if image_data:
        assets_img_dir = os.path.join(site_dir, "assets", "images")
        os.makedirs(assets_img_dir, exist_ok=True)
        for i, (img_bytes, ext) in enumerate(image_data):
            filename = f"customer_img_{i + 1}{ext}"
            with open(os.path.join(assets_img_dir, filename), "wb") as f:
                f.write(img_bytes)

    # Overlay customer logo
    if logo_bytes and logo_ext:
        assets_img_dir = os.path.join(site_dir, "assets", "images")
        os.makedirs(assets_img_dir, exist_ok=True)
        logo_filename = f"customer_logo{logo_ext}"
        with open(os.path.join(assets_img_dir, logo_filename), "wb") as f:
            f.write(logo_bytes)

        # Inject logo into HTML
        index_path = os.path.join(site_dir, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        logo_rel = f"assets/images/{logo_filename}"
        logo_img = f'<img src="{logo_rel}" alt="Logo" style="height:40px;width:auto;object-fit:contain;">'
        footer_logo_img = f'<img src="{logo_rel}" alt="Logo" style="height:32px;width:auto;object-fit:contain;">'
        html = re.sub(
            r'(<(?:a|div)[^>]*class="[^"]*nav-logo[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div)>)',
            r'\g<1>' + logo_img + r'\g<3>',
            html, flags=re.IGNORECASE, count=1,
        )
        html = re.sub(
            r'(<(?:a|div|span)[^>]*class="[^"]*(?:contact-logo|footer-logo(?:-text)?)[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div|span)>)',
            r'\g<1>' + footer_logo_img + r'\g<3>',
            html, flags=re.IGNORECASE, count=1,
        )

        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)

    return site_dir


@app.route("/api/check-domains", methods=["POST"])
def check_domains():
    """Check domain availability via RDAP / DNS."""
    import socket
    import urllib.request
    import urllib.error

    data = request.get_json()
    domains = data.get("domains", [])
    if not domains:
        return jsonify({"error": "No domains provided"}), 400

    results = []
    for domain in domains[:10]:
        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
        available = None
        try:
            if tld == "ch":
                rdap_url = f"https://rdap.nic.ch/domain/{domain}"
            elif tld == "com":
                rdap_url = f"https://rdap.verisign.com/com/v1/domain/{domain}"
            else:
                rdap_url = None

            if rdap_url:
                req = urllib.request.Request(rdap_url)
                try:
                    urllib.request.urlopen(req, timeout=5)
                    available = False  # 200 = registered
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        available = True  # 404 = available
                except Exception:
                    pass
        except Exception:
            pass

        # Fallback: DNS check
        if available is None:
            try:
                socket.getaddrinfo(domain, None)
                available = False
            except socket.gaierror:
                available = True

        results.append({"domain": domain, "available": available, "tld": f".{tld}"})

    return jsonify({"results": results})


@app.route("/api/upload-temp", methods=["POST"])
def upload_temp():
    """Upload files to temp storage for preview. Returns serving URLs."""
    urls = {}
    for key in request.files:
        files = request.files.getlist(key)
        file_urls = []
        for f in files:
            if f.filename:
                ext = os.path.splitext(f.filename)[1] or ".png"
                filename = f"{uuid.uuid4().hex}{ext}"
                filepath = os.path.join(TEMP_UPLOAD_DIR, filename)
                f.save(filepath)
                file_urls.append(f"/api/temp/{filename}")
        if len(file_urls) == 1 and key == "logo":
            urls[key] = file_urls[0]
        else:
            urls[key] = file_urls
    return jsonify(urls)


@app.route("/api/temp/<filename>")
def serve_temp(filename):
    """Serve a temp uploaded file."""
    return send_from_directory(TEMP_UPLOAD_DIR, filename)


@app.route("/api/preview-with-images", methods=["POST"])
def preview_with_images():
    """Generate a self-contained HTML preview using the new generation pipeline."""
    template_key = request.form.get("template", "")
    lead_id = request.form.get("lead_id", "")
    description = request.form.get("description", "")
    values = request.form.get("values", "")

    if template_key not in TEMPLATE_DIRS:
        return "Template not found", 404

    gen_mod = _gen_modules.get(template_key)
    if not gen_mod:
        return "Generation module not found", 500

    # Get lead data
    lead = _preview_lead_cache.get(lead_id)
    if not lead:
        try:
            _, worksheet = open_sheet()
            lead = find_lead_by_id(worksheet, lead_id)
            if lead:
                _preview_lead_cache[lead_id] = lead
        except Exception as e:
            print(f"Preview sheet error: {e}")

    # Build placeholder data from lead + anpassen customizations
    cust = {"description": description, "values": values}
    placeholder_data = _lead_to_placeholder_data(lead, cust) if lead else {}
    if description:
        placeholder_data["ABOUT_DESCRIPTION"] = description
        placeholder_data["HERO_DESCRIPTION"] = description

    # Process uploaded images — convert to data URLs for inline preview
    import base64 as b64mod
    image_files = request.files.getlist("images")
    image_data_urls = []
    for img in image_files:
        if img and img.filename:
            img_bytes = img.read()
            if img_bytes:
                img_b64 = b64mod.b64encode(img_bytes).decode()
                img_mime = img.content_type or "image/png"
                image_data_urls.append(f"data:{img_mime};base64,{img_b64}")

    # Override IMAGE_* placeholders with uploaded images (data URLs)
    if image_data_urls:
        slot_map = getattr(gen_mod, "IMAGE_SLOT_MAP", {})
        image_keys = list(slot_map.keys())
        for i, data_url in enumerate(image_data_urls):
            if i < len(image_keys):
                placeholder_data[image_keys[i]] = data_url

    # Get merged data with enrichment + Pexels images for unfilled slots
    merged = gen_mod.merge_with_defaults(placeholder_data)

    # Read template HTML and replace all placeholders
    template_path = os.path.join(PROJECT_ROOT, TEMPLATE_DIRS[template_key], "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    for key, value in merged.items():
        html = html.replace("{{" + key + "}}", str(value))
    html = re.sub(r"\{\{[A-Z_0-9]+\}\}", "", html)

    # Fix relative asset paths for non-image assets (CSS, JS, fonts)
    base_path = "/" + TEMPLATE_DIRS[template_key] + "/"
    html = html.replace('href="styles.css"', f'href="{base_path}styles.css"')
    html = html.replace('href="./styles.css"', f'href="{base_path}styles.css"')

    # Process logo
    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        logo_bytes = logo_file.read()
        if logo_bytes:
            logo_b64 = b64mod.b64encode(logo_bytes).decode()
            logo_mime = logo_file.content_type or "image/png"
            logo_data_url = f"data:{logo_mime};base64,{logo_b64}"
            logo_img = f'<img src="{logo_data_url}" alt="Logo" style="height:40px;width:auto;object-fit:contain;">'
            footer_logo = f'<img src="{logo_data_url}" alt="Logo" style="height:32px;width:auto;object-fit:contain;">'
            html = re.sub(
                r'(<(?:a|div)[^>]*class="[^"]*nav-logo[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div)>)',
                r'\g<1>' + logo_img + r'\g<3>', html, flags=re.IGNORECASE, count=1)
            html = re.sub(
                r'(<(?:a|div|span)[^>]*class="[^"]*(?:contact-logo|footer-logo(?:-text)?)[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div|span)>)',
                r'\g<1>' + footer_logo + r'\g<3>', html, flags=re.IGNORECASE, count=1)

    # Inline CSS so srcdoc is self-contained
    css_path = os.path.join(PROJECT_ROOT, TEMPLATE_DIRS[template_key], "styles.css")
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()
        html = re.sub(r'<link[^>]*href="[^"]*style[^"]*\.css"[^>]*>', f'<style>{css}</style>', html, flags=re.IGNORECASE)

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/preview/<lead_id>/<template_key>")
def serve_preview(lead_id, template_key):
    """Serve a template preview using the new generation pipeline (enrichment + Pexels)."""
    if template_key not in TEMPLATE_DIRS:
        return "Template not found", 404

    gen_mod = _gen_modules.get(template_key)

    # Get lead data (use cache to avoid repeated sheet calls for assets)
    lead = _preview_lead_cache.get(lead_id)
    if not lead:
        try:
            _, worksheet = open_sheet()
            lead = find_lead_by_id(worksheet, lead_id)
            if lead:
                _preview_lead_cache[lead_id] = lead
        except Exception as e:
            print(f"Preview sheet error: {e}")

    # Read customizations from query params
    customizations = {
        "description": request.args.get("description", ""),
        "values": request.args.get("values", ""),
    }
    logo_url = request.args.get("logo", "")
    image_urls = request.args.getlist("img")

    # Build placeholder data from lead + customizations
    placeholder_data = _lead_to_placeholder_data(lead, customizations) if lead else {}

    # Override IMAGE_* with uploaded image URLs if provided
    if image_urls and gen_mod:
        slot_map = getattr(gen_mod, "IMAGE_SLOT_MAP", {})
        image_keys = list(slot_map.keys())
        for i, url in enumerate(image_urls):
            if i < len(image_keys):
                placeholder_data[image_keys[i]] = url

    # Get merged data with enrichment + Pexels images
    if gen_mod:
        merged = gen_mod.merge_with_defaults(placeholder_data)
    else:
        merged = placeholder_data

    # Read template HTML and replace all placeholders
    template_path = os.path.join(PROJECT_ROOT, TEMPLATE_DIRS[template_key], "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    for key, value in merged.items():
        html = html.replace("{{" + key + "}}", str(value))
    html = re.sub(r"\{\{[A-Z_0-9]+\}\}", "", html)

    # Fix relative asset paths to point to the template directory
    base_path = "/" + TEMPLATE_DIRS[template_key] + "/"
    html = html.replace('href="styles.css"', f'href="{base_path}styles.css"')
    html = html.replace('href="./styles.css"', f'href="{base_path}styles.css"')
    # Image src values are now Pexels URLs or data URLs from placeholder fill, no need
    # to rewrite them. Only rewrite remaining relative asset paths (fonts, JS, etc.)
    html = re.sub(r'src="(assets/(?!images)[^"]*)"', f'src="{base_path}\\1"', html)

    # Replace logo with uploaded logo if provided
    if logo_url:
        logo_img = f'<img src="{logo_url}" alt="Logo" style="height:40px;width:auto;object-fit:contain;">'
        html = re.sub(
            r'(<(?:a|div)[^>]*class="[^"]*nav-logo[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div)>)',
            r'\g<1>' + logo_img + r'\g<3>', html, flags=re.IGNORECASE, count=1)
        footer_logo = f'<img src="{logo_url}" alt="Logo" style="height:32px;width:auto;object-fit:contain;">'
        html = re.sub(
            r'(<(?:a|div|span)[^>]*class="[^"]*(?:contact-logo|footer-logo(?:-text)?)[^"]*"[^>]*>)([\s\S]*?)(</(?:a|div|span)>)',
            r'\g<1>' + footer_logo + r'\g<3>', html, flags=re.IGNORECASE, count=1)

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/preview/<lead_id>/<template_key>/<path:asset_path>")
def serve_preview_asset(lead_id, template_key, asset_path):
    """Serve static assets (CSS, images, JS) for template previews."""
    if template_key not in TEMPLATE_DIRS:
        return "Not found", 404
    return send_from_directory(TEMPLATE_DIRS[template_key], asset_path)


# ============================================================
#  Static file serving
# ============================================================

@app.route("/")
def serve_index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.route("/dashboard")
@app.route("/dashboard/")
def serve_dashboard():
    return send_from_directory(PROJECT_ROOT, "dashboard.html")


@app.route("/dashboard/<path:path>")
def serve_dashboard_static(path):
    """Serve dashboard static assets (CSS, JS, fonts)."""
    return send_from_directory(PROJECT_ROOT, path)


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(PROJECT_ROOT, path)


# ============================================================
#  Startup
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  Dashboard API Server")
    print(f"  http://localhost:8090")
    print(f"  Sheet: {CANONICAL_SHEET_URL[:60]}..." if CANONICAL_SHEET_URL else "  ⚠ LEADS_SHEET_URL not set!")
    print("=" * 50)
    port = int(os.environ.get("PORT", 8090))
    app.run(host="0.0.0.0", port=port, debug=True)
