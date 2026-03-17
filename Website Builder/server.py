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
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, send_file

import gspread

# --- Path setup (same pattern as pipeline_manager.py) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from execution.google_auth import get_credentials

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

    return jsonify({
        "success": True,
        "message": "Bestellung erfolgreich!",
        "drive_folder": drive_folder_url,
    })


# ============================================================
#  Template Preview — serve templates with real business data
# ============================================================

TEMPLATE_DIRS = {
    "earlydog": ".claude/skills/build-website-earlydog/template",
    "bia": ".claude/skills/build-website-bia/template",
    "liveblocks": ".claude/skills/build-website-liveblocks/template",
    "loveseen": ".claude/skills/build-website-loveseen/template",
}

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


@app.route("/api/preview/<lead_id>/<template_key>")
def serve_preview(lead_id, template_key):
    """Serve a template with placeholders replaced by real lead data + customizations."""
    if template_key not in TEMPLATE_DIRS:
        return "Template not found", 404

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

    if not lead:
        # No lead found — still serve template with path rewriting so CSS/assets load
        template_path = os.path.join(PROJECT_ROOT, TEMPLATE_DIRS[template_key], "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        # Fix relative asset paths to absolute
        base_path = "/" + TEMPLATE_DIRS[template_key] + "/"
        html = html.replace('src="assets/', f'src="{base_path}assets/')
        html = html.replace("src='assets/", f"src='{base_path}assets/")
        html = html.replace('href="assets/', f'href="{base_path}assets/')
        html = html.replace('href="style', f'href="{base_path}style')
        html = html.replace('href="./style', f'href="{base_path}style')
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    # Read customizations from query params
    customizations = {
        "description": request.args.get("description", ""),
        "values": request.args.get("values", ""),
    }
    logo_url = request.args.get("logo", "")
    image_urls = request.args.getlist("img")

    # Read template HTML
    template_path = os.path.join(PROJECT_ROOT, TEMPLATE_DIRS[template_key], "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace all {{PLACEHOLDER}} patterns
    # Try AI-powered content generation if API key is available and customizations provided
    replacements = None
    if customizations.get("description") or customizations.get("values"):
        replacements = _generate_content_with_ai(lead, template_key, customizations)
    # Fallback to static replacement if AI is unavailable
    if not replacements:
        replacements = _build_replacements(lead, customizations)
    for key, value in replacements.items():
        html = html.replace("{{" + key + "}}", value)

    # Replace any remaining {{...}} with empty string
    html = re.sub(r"\{\{[A-Z_0-9]+\}\}", "", html)

    # Fix relative asset paths to point to the template directory
    base_path = "/" + TEMPLATE_DIRS[template_key] + "/"
    html = html.replace('src="assets/', f'src="{base_path}assets/')
    html = html.replace("src='assets/", f"src='{base_path}assets/")
    html = html.replace('href="assets/', f'href="{base_path}assets/')
    html = html.replace('href="style', f'href="{base_path}style')
    html = html.replace('href="./style', f'href="{base_path}style')

    # Replace images with uploaded files
    if logo_url or image_urls:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Replace nav logo with uploaded logo image
        if logo_url:
            nav_logo = soup.select_one(".nav-logo")
            if nav_logo:
                # Clear existing content (text or inline SVG) and insert img
                nav_logo.clear()
                logo_img = soup.new_tag("img", src=logo_url, alt="Logo")
                logo_img["style"] = "height: 40px; width: auto; object-fit: contain;"
                nav_logo.append(logo_img)
            # Also replace footer logo if present
            footer_logo = soup.select_one(".footer-logo, .footer-logo-text")
            if footer_logo:
                footer_logo.clear()
                flogo_img = soup.new_tag("img", src=logo_url, alt="Logo")
                flogo_img["style"] = "height: 32px; width: auto; object-fit: contain;"
                footer_logo.append(flogo_img)

        # Replace SVG placeholder images with uploaded images
        if image_urls:
            img_tags = soup.find_all("img")
            svg_imgs = [img for img in img_tags if img.get("src", "").endswith(".svg")]
            for i, url in enumerate(image_urls):
                if i < len(svg_imgs):
                    svg_imgs[i]["src"] = url
                    svg_imgs[i]["style"] = "object-fit: cover; width: 100%; height: 100%;"

        html = str(soup)

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
