#!/usr/bin/env python3
"""
Generate personalized German cold emails for businesses without websites.

Produces 3 email variants:
- Day 0: Cold intro with 3 live website links
- Day 7: Follow-up with different angle
- Day 14: Breakup email

All emails are in German, under 120 words, with one clear CTA.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for shared utils
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate


def generate_greeting(owner_name: str | None, business_name: str) -> str:
    """Generate a personal or generic greeting."""
    if owner_name and owner_name.strip():
        return f"Grüezi {owner_name}"
    return f"Grüezi"


def generate_day0_email(
    business_name: str,
    category: str,
    city: str,
    owner_name: str | None,
    url1: str,
    url2: str,
    url3: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 0 cold intro email."""
    greeting = generate_greeting(owner_name, business_name)

    subject = f"3 Website-Entwürfe für {business_name}"

    body = f"""{greeting}

Mir ist aufgefallen, dass {business_name} in {city} noch keine eigene Website hat — obwohl viele Kunden heute zuerst online suchen.

Deshalb habe ich mir erlaubt, 3 Website-Entwürfe für Sie zu erstellen:

Design 1 (Klassisch): {url1}
Design 2 (Modern): {url2}
Design 3 (Frisch): {url3}

Alle 3 Entwürfe enthalten bereits Ihren Firmennamen, Adresse und Telefonnummer.

Welches Design gefällt Ihnen am besten? Antworten Sie einfach kurz auf diese E-Mail — oder rufen Sie mich an.

Freundliche Grüsse
{sender_name}
{sender_phone}
{sender_email}"""

    return {
        "variant": "day_0_cold_intro",
        "day": 0,
        "subject": subject,
        "body": body,
        "description": "Cold intro — show 3 live website drafts, ask which they prefer",
    }


def generate_day7_email(
    business_name: str,
    category: str,
    city: str,
    owner_name: str | None,
    url1: str,
    url2: str,
    url3: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 7 follow-up email."""
    greeting = generate_greeting(owner_name, business_name)

    subject = f"Kurze Nachfrage — Website für {business_name}"

    body = f"""{greeting}

Ich habe Ihnen letzte Woche 3 Website-Entwürfe für {business_name} geschickt. Vielleicht ist die Nachricht untergegangen — deshalb hier nochmal die Links:

Design 1: {url1}
Design 2: {url2}
Design 3: {url3}

Andere {category}-Betriebe in der Region haben bereits eine professionelle Website. Eine eigene Online-Präsenz kann Ihnen helfen, neue Kunden zu gewinnen.

Falls Ihnen eines der Designs zusagt, lassen Sie es mich einfach wissen.

Freundliche Grüsse
{sender_name}
{sender_phone}"""

    return {
        "variant": "day_7_followup",
        "day": 7,
        "subject": subject,
        "body": body,
        "description": "Follow-up — resend links with social proof angle",
    }


def generate_day14_email(
    business_name: str,
    category: str,
    city: str,
    owner_name: str | None,
    url1: str,
    sender_name: str,
    sender_phone: str,
    sender_email: str,
) -> dict:
    """Generate the Day 14 breakup email."""
    greeting = generate_greeting(owner_name, business_name)

    subject = f"Letzte Nachricht — {business_name} Website"

    body = f"""{greeting}

Die 3 Website-Entwürfe für {business_name} sind noch online — aber ich werde sie bald einem anderen Betrieb anbieten.

Falls Sie doch Interesse haben, antworten Sie einfach mit "Interesse" — dann reserviere ich die Seite für Sie.

Falls nicht, kein Problem. Ich wünsche Ihnen weiterhin viel Erfolg!

Freundliche Grüsse
{sender_name}
{sender_phone}"""

    return {
        "variant": "day_14_breakup",
        "day": 14,
        "subject": subject,
        "body": body,
        "description": "Breakup — last chance, low pressure, urgency",
    }


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

    # Find row
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
    parser.add_argument("--website-url-1", required=True, help="Live URL for template 1 (Klassisch)")
    parser.add_argument("--website-url-2", required=True, help="Live URL for template 2 (Modern)")
    parser.add_argument("--website-url-3", required=True, help="Live URL for template 3 (Frisch)")
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--sender-phone", required=True)
    parser.add_argument("--sender-email", required=True)
    parser.add_argument("--owner-email", default="", help="Recipient email address")
    parser.add_argument("--sheet-url", help="Google Sheet URL to update status")
    parser.add_argument("--lead-id", help="Lead ID for sheet update")
    args = parser.parse_args()

    # Generate all 3 variants
    emails = []

    emails.append(generate_day0_email(
        args.business_name, args.category, args.city, args.owner_name,
        args.website_url_1, args.website_url_2, args.website_url_3,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    emails.append(generate_day7_email(
        args.business_name, args.category, args.city, args.owner_name,
        args.website_url_1, args.website_url_2, args.website_url_3,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    emails.append(generate_day14_email(
        args.business_name, args.category, args.city, args.owner_name,
        args.website_url_1,
        args.sender_name, args.sender_phone, args.sender_email,
    ))

    # Output
    result = {
        "generated_at": datetime.now().isoformat(),
        "recipient": {
            "business_name": args.business_name,
            "owner_name": args.owner_name,
            "owner_email": args.owner_email,
            "city": args.city,
            "category": args.category,
        },
        "sender": {
            "name": args.sender_name,
            "phone": args.sender_phone,
            "email": args.sender_email,
        },
        "emails": emails,
    }

    # Save to .tmp
    output_path = save_intermediate(result, "cold_emails")

    # Print emails
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

    # Update sheet
    if args.sheet_url and args.lead_id:
        print(f"\nUpdating Google Sheet...")
        update_sheet_status(args.sheet_url, args.lead_id)

    # JSON output
    print(f"\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
