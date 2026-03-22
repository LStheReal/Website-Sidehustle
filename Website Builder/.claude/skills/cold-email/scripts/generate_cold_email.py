#!/usr/bin/env python3
"""
Generate personalized German cold emails for businesses without websites.

Produces 3 email variants:
- Day 0: Cold intro with 4 live website links in a 2x2 image grid + claim code
- Day 7: Follow-up with different angle
- Day 14: Breakup email

All emails are in German, personal tone ("Sie"/"Ihr"), one clear CTA.
Day 0 is HTML with clickable screenshot grid. Day 7 + 14 are plain text.
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Add project root to path for shared utils
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate


def get_screenshot_url(website_url: str, custom_url: str | None = None) -> str:
    """Return a screenshot image URL. Auto-generates via thum.io if no custom URL given."""
    if custom_url and custom_url.strip():
        return custom_url
    return f"https://image.thum.io/get/width/280/{website_url}"


def capture_screenshot_bytes(url: str) -> bytes:
    """Capture a 1280x800 screenshot of url using Playwright, return PNG bytes."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            page.goto(url, timeout=20000)
        data = page.screenshot(full_page=False)
        browser.close()
        return data


def generate_greeting(owner_name: str | None) -> str:
    if owner_name and owner_name.strip():
        return f"Grüezi {owner_name}"
    return "Grüezi"


def generate_day0_email(
    business_name: str,
    owner_name: str | None,
    url1: str, url2: str, url3: str, url4: str,
    ss1: str, ss2: str, ss3: str, ss4: str,
    lead_id: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 0 cold intro email (HTML with 2x2 image grid + claim code)."""
    greeting = generate_greeting(owner_name)
    claim_url = f"https://meine-kmu.ch/dashboard"

    subject = "Grüezi, wir haben 4 Webseiten für Sie gebaut"

    # --- HTML version ---
    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @import url('https://api.fontshare.com/v2/css?f[]=clash-display@700&display=swap');
  </style>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; max-width: 580px; margin: 0 auto; padding: 0; color: #333; line-height: 1.6;">

  <!-- Header -->
  <div style="background: #1a1a1a; padding: 18px 24px;">
    <a href="https://meine-kmu.ch" target="_blank" style="text-decoration: none;">
      <span style="color: #fff; font-size: 22px; font-weight: 800; letter-spacing: -0.5px; font-family: 'ClashDisplay', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;">meine-kmu<span style="color: #a6ff00;">.</span></span>
    </a>
  </div>

  <!-- Body -->
  <div style="padding: 28px 24px;">

    <p style="margin-top: 0;">{greeting}</p>

    <p>Wir haben festgestellt, dass Ihr Betrieb noch keine Webseite hat. Deshalb haben wir Ihnen gleich 4 erstellt.</p>

    <p>Heute suchen über 80% der Kunden zuerst online nach einem Betrieb. Eine eigene Webseite macht Sie sichtbar und weckt Vertrauen, noch bevor jemand anruft.</p>

    <p>Klicken Sie auf ein Design, um es anzuschauen:</p>

    <!-- 2x2 screenshot grid -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin: 20px 0;">
      <tr>
        <td width="50%" style="padding: 5px;">
          <a href="{url1}" target="_blank" style="display: block; text-decoration: none; color: #444;">
            <img src="cid:ss1" width="100%" style="border: 1px solid #ddd; border-radius: 5px; display: block;" alt="Klassisch">
            <div style="text-align: center; font-size: 12px; margin-top: 6px; font-weight: 600;">Klassisch →</div>
          </a>
        </td>
        <td width="50%" style="padding: 5px;">
          <a href="{url2}" target="_blank" style="display: block; text-decoration: none; color: #444;">
            <img src="cid:ss2" width="100%" style="border: 1px solid #ddd; border-radius: 5px; display: block;" alt="Modern">
            <div style="text-align: center; font-size: 12px; margin-top: 6px; font-weight: 600;">Modern →</div>
          </a>
        </td>
      </tr>
      <tr>
        <td width="50%" style="padding: 5px;">
          <a href="{url3}" target="_blank" style="display: block; text-decoration: none; color: #444;">
            <img src="cid:ss3" width="100%" style="border: 1px solid #ddd; border-radius: 5px; display: block;" alt="Frisch">
            <div style="text-align: center; font-size: 12px; margin-top: 6px; font-weight: 600;">Frisch →</div>
          </a>
        </td>
        <td width="50%" style="padding: 5px;">
          <a href="{url4}" target="_blank" style="display: block; text-decoration: none; color: #444;">
            <img src="cid:ss4" width="100%" style="border: 1px solid #ddd; border-radius: 5px; display: block;" alt="Elegant">
            <div style="text-align: center; font-size: 12px; margin-top: 6px; font-weight: 600;">Elegant →</div>
          </a>
        </td>
      </tr>
    </table>

    <p>Jedes Design ist vollständig nach Ihren Wünschen anpassbar: Farben, Texte, Bilder und Logo. Kein Technik-Wissen nötig.</p>

    <p>Gefällt Ihnen eine davon? Erhalten Sie Zugriff auf <strong>meine-kmu.ch</strong> mit Ihrem persönlichen Code:</p>

    <!-- Claim code box -->
    <div style="background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 8px; padding: 22px; margin: 20px 0; text-align: center;">
      <div style="font-size: 11px; color: #999; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1.5px;">Ihr persönlicher Code</div>
      <div style="font-size: 30px; font-weight: bold; letter-spacing: 6px; color: #1a1a1a; margin-bottom: 16px;">{lead_id}</div>
      <a href="{claim_url}" style="background: #1a1a1a; color: #fff; padding: 11px 26px; border-radius: 4px; text-decoration: none; font-size: 14px; font-weight: 600; display: inline-block;">Zugriff erhalten →</a>
    </div>

    <p>Bei Fragen antworten Sie einfach auf diese E-Mail.</p>

    <p style="margin-bottom: 0;">Freundliche Grüsse<br>
    <strong>{sender_name}</strong><br>
    <span style="color: #555;">{sender_email}</span><br>
    <span style="color: #555;">{sender_phone}</span><br>
    <a href="https://meine-kmu.ch" style="color: #555;">meine-kmu.ch</a></p>

  </div>

</body>
</html>"""

    # --- Plain text fallback ---
    body_text = f"""{greeting}

Wir haben festgestellt, dass Ihr Betrieb noch keine Webseite hat. Deshalb haben wir Ihnen gleich 4 erstellt.

Heute suchen über 80% der Kunden zuerst online nach einem Betrieb. Eine eigene Webseite macht Sie sichtbar und weckt Vertrauen, noch bevor jemand anruft.

Schauen Sie sich die Designs an:

Klassisch: {url1}
Modern:    {url2}
Frisch:    {url3}
Elegant:   {url4}

Gefällt Ihnen eine davon? Erhalten Sie Zugriff auf meine-kmu.ch mit Ihrem persönlichen Code:

  Code: {lead_id}
  Link: {claim_url}

Jedes Design ist vollständig nach Ihren Wünschen anpassbar — Farben, Texte, Bilder und Logo. Kein Technik-Wissen nötig.

Bei Fragen antworten Sie einfach auf diese E-Mail.

Freundliche Grüsse
{sender_name}
{sender_email}
{sender_phone}
meine-kmu.ch"""

    return {
        "variant": "day_0_cold_intro",
        "day": 0,
        "subject": subject,
        "body": body_text,
        "body_html": body_html,
        "description": "Cold intro — 4 website screenshots in 2x2 grid + claim code for meine-kmu.ch",
    }


def generate_day7_email(
    business_name: str,
    category: str,
    owner_name: str | None,
    url1: str, url2: str, url3: str, url4: str,
    lead_id: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 7 follow-up email."""
    greeting = generate_greeting(owner_name)
    claim_url = f"https://meine-kmu.ch/dashboard"

    subject = f"Noch kurz nachfragen — {business_name}"

    body = f"""{greeting}

Letzte Woche haben wir Ihnen 4 Website-Entwürfe geschickt — vielleicht ist die Nachricht untergegangen, deshalb nochmal:

Klassisch: {url1}
Modern:    {url2}
Frisch:    {url3}
Elegant:   {url4}

Andere {category}-Betriebe in der Region sind bereits online. Erhalten Sie Zugriff auf Ihre Webseite auf meine-kmu.ch mit Ihrem Code:

  Code: {lead_id}
  {claim_url}

Freundliche Grüsse
{sender_name}
{sender_email}
{sender_phone}"""

    return {
        "variant": "day_7_followup",
        "day": 7,
        "subject": subject,
        "body": body,
        "description": "Follow-up — resend links with social proof, remind of claim code",
    }


def generate_day14_email(
    business_name: str,
    owner_name: str | None,
    lead_id: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 14 breakup email."""
    greeting = generate_greeting(owner_name)
    claim_url = f"https://meine-kmu.ch/dashboard"

    subject = f"Letzte Nachricht — {business_name}"

    body = f"""{greeting}

Die 4 Webseiten-Entwürfe für Ihren Betrieb sind noch online — wir werden sie aber bald einem anderen Betrieb in der Region anbieten.

Falls Sie doch Interesse haben, erhalten Sie jetzt noch schnell Zugriff auf meine-kmu.ch:

  Code: {lead_id}
  {claim_url}

Falls nicht, kein Problem. Wir wünschen Ihnen weiterhin viel Erfolg!

Freundliche Grüsse
{sender_name}
{sender_email}
{sender_phone}"""

    return {
        "variant": "day_14_breakup",
        "day": 14,
        "subject": subject,
        "body": body,
        "description": "Breakup — last chance, urgency, final claim code reminder",
    }


# --- Email sending ---

def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
    from_name: str,
    from_email: str,
    inline_images: list[tuple[bytes, str]] | None = None,
) -> None:
    """Send an HTML email via SMTP. Credentials are read from .env / environment.

    inline_images: list of (png_bytes, cid) tuples — embedded as inline attachments
    and referenced in HTML as <img src="cid:{cid}">.
    """
    from dotenv import load_dotenv
    from email.header import Header
    from email.utils import formataddr
    load_dotenv()

    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")

    if not all([smtp_host, smtp_user, smtp_password]):
        raise RuntimeError(
            "Missing SMTP credentials. Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD in your .env file."
        )

    # Build MIME structure:
    # multipart/related
    #   └── multipart/alternative
    #         ├── text/plain
    #         └── text/html  (references cid:ssN)
    #   ├── image/png  Content-ID: <ss1>
    #   └── ...
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = subject
    msg_root["From"] = formataddr((str(Header(from_name, "utf-8")), from_email))
    msg_root["To"] = to_email
    msg_root["Reply-To"] = from_email

    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(body_text, "plain", "utf-8"))
    msg_alt.attach(MIMEText(body_html, "html", "utf-8"))
    msg_root.attach(msg_alt)

    if inline_images:
        for png_bytes, cid in inline_images:
            img_part = MIMEImage(png_bytes, "png")
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
            msg_root.attach(img_part)

    if smtp_port == 587:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_email, msg_root.as_string())
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_email, msg_root.as_string())

    print(f"  Sent Day 0 email to {to_email}")


# --- Google Sheets integration ---

def update_sheet_status(sheet_url: str, lead_id: str):
    """Update lead status to email_sent with today's date."""
    import gspread
    from dotenv import load_dotenv
    from execution.google_auth import get_credentials
    from gspread.utils import rowcol_to_a1

    load_dotenv()
    creds = get_credentials()
    client = gspread.authorize(creds)

    if "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        sheet_id = sheet_url
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    lead_ids = worksheet.col_values(1)
    row_idx = None
    for i, lid in enumerate(lead_ids):
        if lid == lead_id:
            row_idx = i + 1
            break

    if row_idx is None:
        print(f"  Warning: lead_id '{lead_id}' not found in sheet.")
        return

    COL_STATUS = 21
    COL_EMAIL_SENT_DATE = 26

    cells = [
        {"range": rowcol_to_a1(row_idx, COL_STATUS), "values": [["email_sent"]]},
        {"range": rowcol_to_a1(row_idx, COL_EMAIL_SENT_DATE), "values": [[datetime.now().strftime("%Y-%m-%d")]]},
    ]
    worksheet.batch_update(cells, value_input_option="USER_ENTERED")
    print(f"  Updated sheet: status → email_sent, email_sent_date → {datetime.now().strftime('%Y-%m-%d')}")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Generate cold emails for businesses without websites")
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--category", required=True, help="Business type in German (e.g. Reinigung, Maler)")
    parser.add_argument("--city", required=True)
    parser.add_argument("--owner-name", default="")
    parser.add_argument("--website-url-1", required=True, help="Live URL for template 1 (Klassisch/BiA)")
    parser.add_argument("--website-url-2", required=True, help="Live URL for template 2 (Modern/Liveblocks)")
    parser.add_argument("--website-url-3", required=True, help="Live URL for template 3 (Frisch/Earlydog)")
    parser.add_argument("--website-url-4", required=True, help="Live URL for template 4 (Elegant/Loveseen)")
    parser.add_argument("--screenshot-url-1", default="", help="Screenshot image URL for template 1 (auto-generated if omitted)")
    parser.add_argument("--screenshot-url-2", default="", help="Screenshot image URL for template 2 (auto-generated if omitted)")
    parser.add_argument("--screenshot-url-3", default="", help="Screenshot image URL for template 3 (auto-generated if omitted)")
    parser.add_argument("--screenshot-url-4", default="", help="Screenshot image URL for template 4 (auto-generated if omitted)")
    parser.add_argument("--lead-id", required=True, help="Lead ID used as claim code on meine-kmu.ch")
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--sender-phone", required=True)
    parser.add_argument("--sender-email", required=True)
    parser.add_argument("--owner-email", default="", help="Recipient email address")
    parser.add_argument("--sheet-url", help="Google Sheet URL to update status")
    parser.add_argument("--send", action="store_true", help="Actually send the Day 0 email via SMTP (requires SMTP_* in .env)")
    args = parser.parse_args()

    # Resolve screenshot URLs (auto-generate via thum.io if not provided)
    ss1 = get_screenshot_url(args.website_url_1, args.screenshot_url_1)
    ss2 = get_screenshot_url(args.website_url_2, args.screenshot_url_2)
    ss3 = get_screenshot_url(args.website_url_3, args.screenshot_url_3)
    ss4 = get_screenshot_url(args.website_url_4, args.screenshot_url_4)

    emails = []

    emails.append(generate_day0_email(
        args.business_name, args.owner_name,
        args.website_url_1, args.website_url_2, args.website_url_3, args.website_url_4,
        ss1, ss2, ss3, ss4,
        args.lead_id,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    emails.append(generate_day7_email(
        args.business_name, args.category, args.owner_name,
        args.website_url_1, args.website_url_2, args.website_url_3, args.website_url_4,
        args.lead_id,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    emails.append(generate_day14_email(
        args.business_name, args.owner_name,
        args.lead_id,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    result = {
        "generated_at": datetime.now().isoformat(),
        "recipient": {
            "business_name": args.business_name,
            "owner_name": args.owner_name,
            "owner_email": args.owner_email,
            "city": args.city,
            "category": args.category,
            "lead_id": args.lead_id,
            "claim_url": f"https://meine-kmu.ch/claim?code={args.lead_id}",
        },
        "sender": {
            "name": args.sender_name,
            "phone": args.sender_phone,
            "email": args.sender_email,
        },
        "emails": emails,
    }

    output_path = save_intermediate(result, "cold_emails")

    for email in emails:
        print(f"\n{'='*60}")
        print(f"  {email['variant'].upper()} (Day {email['day']})")
        print(f"  {email['description']}")
        print(f"{'='*60}")
        print(f"  Betreff: {email['subject']}")
        if args.owner_email:
            print(f"  An: {args.owner_email}")
        print(f"{'─'*60}")
        print(email["body"])
        print()

    print(f"Saved to: {output_path}")

    # Send Day 0 email if --send flag is set
    if args.send:
        if not args.owner_email:
            print("\n  Error: --owner-email is required to send the email.")
        else:
            day0 = emails[0]
            print(f"\nCapturing screenshots ...")
            screenshot_urls = [
                args.website_url_1,
                args.website_url_2,
                args.website_url_3,
                args.website_url_4,
            ]
            cids = ["ss1", "ss2", "ss3", "ss4"]
            inline_images = []
            for url, cid in zip(screenshot_urls, cids):
                print(f"  Screenshotting {url} ...")
                png_bytes = capture_screenshot_bytes(url)
                inline_images.append((png_bytes, cid))
            print(f"\nSending Day 0 email to {args.owner_email} ...")
            send_email(
                to_email=args.owner_email,
                subject=day0["subject"],
                body_text=day0["body"],
                body_html=day0["body_html"],
                from_name=args.sender_name,
                from_email=args.sender_email,
                inline_images=inline_images,
            )

    if args.sheet_url and args.lead_id:
        print(f"\nUpdating Google Sheet...")
        update_sheet_status(args.sheet_url, args.lead_id)

    print(f"\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
