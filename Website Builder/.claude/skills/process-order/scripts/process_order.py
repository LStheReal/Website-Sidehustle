#!/usr/bin/env python3
"""
Process a confirmed website order end-to-end:

1. Read lead + order data from Google Sheets
2. Verify the pre-built site in .tmp/order_<lead_id>/ (built by server.py at order time)
3. Deploy to a unique Cloudflare Pages subdomain
4. Update Google Sheet with the live URL
5. Send internal notification email to info@meine-kmu.ch
6. Send confirmation email to the lead

The website is NOT rebuilt here — it is built by server.py's _build_order_site()
at the moment the order is submitted, capturing the exact content shown in the preview.

Usage:
    source .venv/bin/activate
    python3 .claude/skills/process-order/scripts/process_order.py --lead-id <12-char-hex>
    python3 .claude/skills/process-order/scripts/process_order.py --lead-id <12-char-hex> --dry-run
"""

import argparse
import json
import os
import re
import smtplib
import subprocess
import sys
import unicodedata
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

import gspread
from dotenv import load_dotenv

# --- Path setup ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[4]   # Website Builder/
sys.path.insert(0, str(PROJECT_ROOT))

from execution.google_auth import get_credentials

load_dotenv(PROJECT_ROOT / ".env")

# --- Column map (mirrors server.py) ---
COL = {
    "lead_id": 1, "scraped_at": 2, "search_query": 3,
    "business_name": 4, "category": 5, "address": 6,
    "city": 7, "state": 8, "zip_code": 9, "phone": 10,
    "google_maps_url": 11, "rating": 12, "review_count": 13,
    "owner_name": 14, "owner_email": 15, "owner_phone": 16,
    "emails": 17, "facebook": 18, "instagram": 19, "linkedin": 20,
    "status": 21, "domain_option_1": 22, "domain_option_1_purchase": 23,
    "domain_option_1_price": 24, "domain_option_2": 25,
    "domain_option_2_purchase": 26, "domain_option_2_price": 27,
    "domain_option_3": 28, "domain_option_3_purchase": 29,
    "domain_option_3_price": 30, "website_url": 31,
    "email_sent_date": 32, "response_date": 33, "notes": 34,
    "draft_url_1": 35, "draft_url_2": 36, "draft_url_3": 37,
    "draft_url_4": 38, "chosen_template": 39,
    "next_action": 40, "next_action_date": 41,
}
COLUMN_NAMES = list(COL.keys())


# ============================================================
#  Google Sheets helpers
# ============================================================

def open_sheet():
    sheet_id = os.getenv("LEADS_SHEET_ID", "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50")
    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet, spreadsheet.sheet1


def find_lead_by_id(worksheet, lead_id: str) -> dict | None:
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
    from gspread.utils import rowcol_to_a1
    cells = []
    for col_name, value in updates.items():
        if col_name not in COL:
            continue
        cells.append({"range": rowcol_to_a1(row_idx, COL[col_name]), "values": [[str(value)]]})
    if cells:
        worksheet.batch_update(cells, value_input_option="USER_ENTERED")


# ============================================================
#  Project name
# ============================================================

def generate_project_name(business_name: str, lead_id: str) -> str:
    """Generate a unique Cloudflare Pages project name from business name + lead ID."""
    name = business_name
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        name = name.replace(old, new).replace(old.upper(), new.capitalize())
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")[:40].rstrip("-") or "kmu"
    suffix = lead_id[:6]
    return f"kmu-{name}-{suffix}"


# ============================================================
#  Cloudflare Pages deployment
# ============================================================

def deploy_to_cloudflare(site_dir: Path, project_name: str) -> str:
    """Deploy site_dir to a Cloudflare Pages project. Returns live URL."""
    print(f"  Creating Cloudflare Pages project '{project_name}'...")
    subprocess.run(
        ["npx", "wrangler", "pages", "project", "create", project_name,
         "--production-branch", "main"],
        capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
    )

    print(f"  Deploying...")
    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", str(site_dir),
         "--project-name", project_name],
        capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        raise RuntimeError(f"Deployment failed:\n{result.stderr}")

    output = result.stdout + "\n" + result.stderr
    url = None
    for line in output.splitlines():
        match = re.search(r"https://[a-z0-9-]+\.pages\.dev", line, re.IGNORECASE)
        if match:
            url = match.group(0)
    return url or f"https://{project_name}.pages.dev"


# ============================================================
#  Domain link helpers
# ============================================================

def domain_purchase_link(domain: str, existing_purchase_link: str) -> str:
    if existing_purchase_link and existing_purchase_link.startswith("http"):
        return existing_purchase_link
    encoded = domain.replace(".", "%2E")
    return f"https://www.namecheap.com/domains/registration/results/?domain={encoded}"


def cloudflare_custom_domain_link(project_name: str) -> str:
    return f"https://dash.cloudflare.com/?to=/:account/pages/view/{project_name}/domains/new"


# ============================================================
#  Email sending
# ============================================================

def _send_email(to_email: str, subject: str, body_text: str, body_html: str):
    smtp_host = os.getenv("SMTP_HOST", "mail.infomaniak.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "info@meine-kmu.ch")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    if not smtp_password:
        raise RuntimeError("SMTP_PASSWORD not set in .env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((str(Header("meine-kmu.ch", "utf-8")), smtp_user))
    msg["To"] = to_email
    msg["Reply-To"] = smtp_user
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    if smtp_port == 587:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())


def _email_header() -> str:
    return """
  <div style="background: #1a1a1a; padding: 18px 24px;">
    <a href="https://meine-kmu.ch" target="_blank" style="text-decoration: none;">
      <span style="color: #fff; font-size: 22px; font-weight: 800; letter-spacing: -0.5px;
        font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;">
        meine-kmu<span style="color: #a6ff00;">.</span>
      </span>
    </a>
  </div>"""


def _email_footer() -> str:
    return """
  <div style="background: #f5f5f5; padding: 16px 24px; font-size: 12px; color: #888;
    border-top: 1px solid #e0e0e0;">
    <p style="margin: 0;">
      meine-kmu.ch &nbsp;·&nbsp;
      <a href="mailto:info@meine-kmu.ch" style="color: #888;">info@meine-kmu.ch</a> &nbsp;·&nbsp;
      <a href="https://meine-kmu.ch" style="color: #888;">meine-kmu.ch</a>
    </p>
  </div>"""


def send_internal_notification(
    lead_id, business_name, lead_email, live_url,
    selected_domain, purchase_link, cf_custom_domain_link, project_name,
):
    subject = f"Neue Bestellung — {business_name} ({lead_id})"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
  max-width: 580px; margin: 0 auto; padding: 0; color: #333; line-height: 1.6;">
{_email_header()}
  <div style="padding: 28px 24px;">
    <h2 style="margin-top: 0; font-size: 20px;">Neue Bestellung eingegangen</h2>
    <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
      <tr><td style="padding: 8px 0; border-bottom: 1px solid #eee; color: #888; width: 40%; font-size: 14px;">Lead ID</td>
          <td style="padding: 8px 0; border-bottom: 1px solid #eee; font-weight: 600; font-size: 14px;">{lead_id}</td></tr>
      <tr><td style="padding: 8px 0; border-bottom: 1px solid #eee; color: #888; font-size: 14px;">Betrieb</td>
          <td style="padding: 8px 0; border-bottom: 1px solid #eee; font-weight: 600; font-size: 14px;">{business_name}</td></tr>
      <tr><td style="padding: 8px 0; border-bottom: 1px solid #eee; color: #888; font-size: 14px;">E-Mail Kunde</td>
          <td style="padding: 8px 0; border-bottom: 1px solid #eee; font-size: 14px;">
            <a href="mailto:{lead_email}" style="color: #1a1a1a;">{lead_email or "—"}</a></td></tr>
      <tr><td style="padding: 8px 0; border-bottom: 1px solid #eee; color: #888; font-size: 14px;">Gewünschte Domain</td>
          <td style="padding: 8px 0; border-bottom: 1px solid #eee; font-size: 14px;">{selected_domain or "—"}</td></tr>
    </table>
    <h3 style="font-size: 16px; margin-bottom: 12px;">Aktionen</h3>
    <table style="width: 100%; border-collapse: collapse;">
      <tr><td style="padding: 10px 0; border-bottom: 1px solid #eee;">
        <div style="font-size: 13px; color: #888; margin-bottom: 4px;">Website (live)</div>
        <a href="{live_url}" style="color: #1a1a1a; font-weight: 600;">{live_url}</a></td></tr>
      <tr><td style="padding: 10px 0; border-bottom: 1px solid #eee;">
        <div style="font-size: 13px; color: #888; margin-bottom: 4px;">Domain kaufen</div>
        <a href="{purchase_link}" style="color: #1a1a1a; font-weight: 600;">{selected_domain or "Domain suchen"} →</a></td></tr>
      <tr><td style="padding: 10px 0;">
        <div style="font-size: 13px; color: #888; margin-bottom: 4px;">Domain mit Website verbinden</div>
        <a href="{cf_custom_domain_link}" style="color: #1a1a1a; font-weight: 600;">Cloudflare Pages → Custom Domain →</a></td></tr>
    </table>
    <div style="background: #f5f5f5; border-radius: 6px; padding: 16px; margin-top: 24px; font-size: 13px; color: #555;">
      <strong>Nächste Schritte:</strong><br>
      1. Domain kaufen (oben)<br>
      2. Domain im Cloudflare Dashboard mit dem Pages-Projekt verbinden<br>
      3. Warten bis DNS propagiert (5–30 min)<br>
      4. Kunden informieren
    </div>
  </div>
{_email_footer()}
</body></html>"""

    text = (
        f"Neue Bestellung — {business_name} ({lead_id})\n\n"
        f"Lead ID:        {lead_id}\n"
        f"Betrieb:        {business_name}\n"
        f"E-Mail Kunde:   {lead_email or '—'}\n"
        f"Domain:         {selected_domain or '—'}\n\n"
        f"Website (live):   {live_url}\n"
        f"Domain kaufen:    {purchase_link}\n"
        f"Domain verbinden: {cf_custom_domain_link}\n"
    )
    _send_email("info@meine-kmu.ch", subject, text, html)
    print("  Internal notification sent to info@meine-kmu.ch")


def send_customer_confirmation(owner_name, business_name, lead_email, selected_domain):
    if not lead_email:
        print("  Warning: no lead email — skipping customer confirmation.")
        return

    greeting = f"Grüezi{' ' + owner_name if owner_name and owner_name.strip() else ''}"
    domain_display = selected_domain or "Ihrer gewünschten Adresse"
    subject = f"Ihre Website ist in Bearbeitung — {business_name}"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>@import url('https://api.fontshare.com/v2/css?f[]=clash-display@700&display=swap');</style>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
  max-width: 580px; margin: 0 auto; padding: 0; color: #333; line-height: 1.6;">
{_email_header()}
  <div style="padding: 28px 24px;">
    <p style="margin-top: 0;">{greeting}</p>
    <p>Vielen Dank für Ihre Bestellung! Wir haben Ihre Angaben erhalten und beginnen jetzt mit der Umsetzung Ihrer Website.</p>
    <div style="background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 8px;
      padding: 22px; margin: 24px 0; text-align: center;">
      <div style="font-size: 11px; color: #999; margin-bottom: 8px;
        text-transform: uppercase; letter-spacing: 1.5px;">Ihre zukünftige Adresse</div>
      <div style="font-size: 24px; font-weight: bold; letter-spacing: 1px;
        color: #1a1a1a; margin-bottom: 12px;">{domain_display}</div>
      <div style="font-size: 14px; color: #555;">
        Ihre Website wird innerhalb von <strong>48 Stunden</strong> auf<br>
        <strong>{domain_display}</strong> live geschaltet.
      </div>
    </div>
    <p style="font-size: 14px; color: #555;">
      Sobald Ihre Website fertig ist, erhalten Sie von uns eine weitere E-Mail mit dem direkten Link.
      Falls Sie in der Zwischenzeit Fragen haben, antworten Sie einfach auf diese E-Mail.
    </p>
    <p style="margin-bottom: 0;">Freundliche Grüsse<br>
    <strong>Das meine-kmu.ch Team</strong><br>
    <a href="mailto:info@meine-kmu.ch" style="color: #555;">info@meine-kmu.ch</a><br>
    <a href="https://meine-kmu.ch" style="color: #555;">meine-kmu.ch</a></p>
  </div>
{_email_footer()}
</body>
</html>"""

    text = (
        f"{greeting}\n\n"
        f"Vielen Dank für Ihre Bestellung!\n\n"
        f"Ihre zukünftige Adresse: {domain_display}\n\n"
        f"Ihre Website wird innerhalb von 48 Stunden auf {domain_display} live geschaltet.\n\n"
        f"Bei Fragen antworten Sie einfach auf diese E-Mail.\n\n"
        f"Freundliche Grüsse\nDas meine-kmu.ch Team\ninfo@meine-kmu.ch\nmeine-kmu.ch"
    )
    _send_email(lead_email, subject, text, html)
    print(f"  Customer confirmation sent to {lead_email}")


# ============================================================
#  Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Deploy a pre-built order and send emails")
    parser.add_argument("--lead-id", required=True, help="12-char hex lead ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without deploying or sending emails")
    args = parser.parse_args()

    lead_id = args.lead_id.strip().lower()
    if not re.match(r"^[a-f0-9]{12}$", lead_id):
        print(f"Error: invalid lead ID '{lead_id}' (must be 12 hex chars)", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Processing order for lead {lead_id} ===")

    # 1. Load lead from sheet
    print("\n[1/5] Loading lead from Google Sheets...")
    _, worksheet = open_sheet()
    lead = find_lead_by_id(worksheet, lead_id)
    if not lead:
        print(f"Error: lead '{lead_id}' not found in sheet.", file=sys.stderr)
        sys.exit(1)

    business_name = lead.get("business_name", lead_id)
    selected_domain = lead.get("domain_option_1", "")
    purchase_link_raw = lead.get("domain_option_1_purchase", "")
    lead_email = lead.get("owner_email") or lead.get("emails", "")
    owner_name = lead.get("owner_name", "")
    row_idx = lead["_row_idx"]

    # Override domain from notes JSON if present
    try:
        notes_data = json.loads(lead.get("notes", "") or "{}")
        if notes_data.get("selected_domain"):
            selected_domain = notes_data["selected_domain"]
    except json.JSONDecodeError:
        pass

    print(f"  Business: {business_name}")
    print(f"  Domain:   {selected_domain or '(none)'}")
    print(f"  Email:    {lead_email or '(none)'}")

    # 2. Verify pre-built site
    print("\n[2/5] Checking pre-built site...")
    site_dir = PROJECT_ROOT / ".tmp" / f"order_{lead_id}"
    if not site_dir.is_dir() or not (site_dir / "index.html").exists():
        print(
            f"Error: pre-built site not found at {site_dir}\n"
            "The site is built automatically when the order is submitted via the dashboard.\n"
            "Make sure server.py processed the order first.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  Found: {site_dir}")

    # 3. Deploy
    project_name = generate_project_name(business_name, lead_id)
    live_url = f"https://{project_name}.pages.dev"

    if args.dry_run:
        print(f"\n[3/5] DRY RUN — would deploy {site_dir} to {live_url}")
    else:
        print(f"\n[3/5] Deploying to Cloudflare Pages (project: {project_name})...")
        live_url = deploy_to_cloudflare(site_dir, project_name)
        print(f"  Live URL: {live_url}")

    # 4. Update sheet
    if args.dry_run:
        print(f"\n[4/5] DRY RUN — would update sheet: website_url={live_url}, status=website_created")
    else:
        print(f"\n[4/5] Updating Google Sheet...")
        update_cells(worksheet, row_idx, {
            "website_url": live_url,
            "status": "website_created",
            "next_action": "CONNECT DOMAIN",
            "next_action_date": datetime.now().strftime("%Y-%m-%d"),
        })
        print(f"  Sheet updated.")

    # 5. Send emails
    purchase_link = domain_purchase_link(selected_domain, purchase_link_raw)
    cf_link = cloudflare_custom_domain_link(project_name)

    if args.dry_run:
        print(f"\n[5/5] DRY RUN — emails would be sent:")
        print(f"  → info@meine-kmu.ch  (internal notification)")
        print(f"  → {lead_email or '(no email)'}  (customer confirmation)")
        print(f"  Live URL:        {live_url}")
        print(f"  Purchase link:   {purchase_link}")
        print(f"  CF domain link:  {cf_link}")
    else:
        print(f"\n[5/5] Sending emails...")
        send_internal_notification(
            lead_id=lead_id, business_name=business_name, lead_email=lead_email,
            live_url=live_url, selected_domain=selected_domain,
            purchase_link=purchase_link, cf_custom_domain_link=cf_link,
            project_name=project_name,
        )
        send_customer_confirmation(
            owner_name=owner_name, business_name=business_name,
            lead_email=lead_email, selected_domain=selected_domain,
        )

    print(f"\n=== Done ===")
    print(f"  Live URL: {live_url}")


if __name__ == "__main__":
    main()
