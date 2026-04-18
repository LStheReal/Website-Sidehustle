#!/usr/bin/env python3
"""
WhatsApp Outreach — Generate personalized wa.me links for lead outreach.

Generates clickable wa.me deep links that open WhatsApp pre-filled with a
personalized German message. User clicks link → WhatsApp opens → tap Send.

Supports three message variants:
  day0       — First contact with 4 website links
  post_call  — "Wie besprochen" after phone call
  followup   — Day 7 reminder

Usage:
    # Single lead
    python3 send_whatsapp.py --phone "+41 44 123 45 67" --business-name "Coiffeur Züri" \\
        --url-1 "https://..." --url-2 "https://..." --url-3 "https://..." --url-4 "https://..." \\
        --sender-name "Louise"

    # Batch mode (reads from Google Sheet, prints all wa.me links)
    python3 send_whatsapp.py --batch --sheet-id "1ewww..." --sender-name "Louise" --variant day0
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate


def format_swiss_phone(phone: str) -> str:
    """
    Normalize Swiss phone number to international format for wa.me links.

    Handles:
        +41 44 123 45 67  →  41441234567
        044 123 45 67     →  41441234567
        0041 44 123 45 67 →  41441234567
        +41441234567      →  41441234567
        079 123 45 67     →  41791234567

    Returns empty string if phone can't be parsed.
    """
    if not phone:
        return ""

    # Strip all whitespace, dashes, dots, parens
    cleaned = re.sub(r"[\s\-\.\(\)]+", "", phone)

    # Remove leading + if present
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # 0041... → 41...
    if cleaned.startswith("0041"):
        cleaned = cleaned[4:]
        cleaned = "41" + cleaned

    # 0XX... (local Swiss) → 41XX...
    elif cleaned.startswith("0") and len(cleaned) >= 10:
        cleaned = "41" + cleaned[1:]

    # Already starts with 41
    elif cleaned.startswith("41"):
        pass
    else:
        # Unknown format — return as-is without country code handling
        pass

    # Validate: should be 11 digits for Swiss numbers (41 + 9 digits)
    if re.match(r"^41\d{9}$", cleaned):
        return cleaned

    # Fallback: return whatever we have if it's all digits
    if cleaned.isdigit() and len(cleaned) >= 10:
        return cleaned

    return ""


def generate_whatsapp_message(
    business_name: str,
    owner_name: str | None,
    url1: str,
    url2: str,
    url3: str,
    url4: str,
    sender_name: str,
    variant: str = "day0",
) -> str:
    """
    Generate a personalized German WhatsApp message.

    Args:
        business_name: Name of the business
        owner_name: Owner's name (optional, for greeting)
        url1-url4: Four draft website URLs
        sender_name: Your name
        variant: "day0", "post_call", or "followup"

    Returns:
        Message text ready for WhatsApp
    """
    greeting = f"Grüezi {owner_name}" if owner_name and owner_name.strip() else "Grüezi"

    if variant == "day0":
        return (
            f"{greeting}, hier ist {sender_name} von meine-kmu.ch.\n"
            f"\n"
            f"Wir haben 4 kostenlose Website-Entwürfe für {business_name} erstellt:\n"
            f"\n"
            f"1) {url1}\n"
            f"2) {url2}\n"
            f"3) {url3}\n"
            f"4) {url4}\n"
            f"\n"
            f"Einfach anschauen — kostenlos und unverbindlich!\n"
            f"Welches Design gefällt Ihnen am besten?"
        )

    elif variant == "post_call":
        return (
            f"{greeting}, wie besprochen hier die 4 Website-Entwürfe für {business_name}:\n"
            f"\n"
            f"1) {url1}\n"
            f"2) {url2}\n"
            f"3) {url3}\n"
            f"4) {url4}\n"
            f"\n"
            f"Welches Design gefällt Ihnen? Einfach antworten!"
        )

    elif variant == "followup":
        return (
            f"{greeting}, kurze Erinnerung — haben Sie die Website-Entwürfe "
            f"für {business_name} schon gesehen?\n"
            f"\n"
            f"1) {url1}\n"
            f"2) {url2}\n"
            f"3) {url3}\n"
            f"4) {url4}\n"
            f"\n"
            f"Keine Verpflichtung — einfach kurz reinschauen!"
        )

    else:
        raise ValueError(f"Unknown variant: {variant}. Use day0, post_call, or followup.")


def generate_wa_me_link(phone: str, message: str) -> str:
    """
    Build a clickable wa.me deep link.

    Args:
        phone: International format phone (digits only, e.g. "41441234567")
        message: Message text to pre-fill

    Returns:
        URL like https://wa.me/41441234567?text=...
    """
    encoded = quote(message, safe="")
    return f"https://wa.me/{phone}?text={encoded}"


def generate_for_lead(
    lead: dict,
    sender_name: str,
    variant: str = "day0",
) -> dict:
    """
    Generate WhatsApp outreach for a single lead dict (from Google Sheet).

    Args:
        lead: Dict with keys: business_name, phone, owner_name, draft_url_1..4
        sender_name: Your name
        variant: Message variant

    Returns:
        Dict with: business_name, phone, formatted_phone, message, wa_me_link, variant
    """
    phone_raw = lead.get("phone", "")
    formatted_phone = format_swiss_phone(phone_raw)

    if not formatted_phone:
        return {
            "business_name": lead.get("business_name", "?"),
            "phone": phone_raw,
            "error": f"Could not parse phone number: {phone_raw}",
        }

    urls = [
        lead.get("draft_url_1", "") or lead.get("url_earlydog", ""),
        lead.get("draft_url_2", "") or lead.get("url_bia", ""),
        lead.get("draft_url_3", "") or lead.get("url_liveblocks", ""),
        lead.get("draft_url_4", "") or lead.get("url_loveseen", ""),
    ]

    # Filter out empty URLs
    valid_urls = [u for u in urls if u.strip()]
    if not valid_urls:
        return {
            "business_name": lead.get("business_name", "?"),
            "phone": phone_raw,
            "error": "No draft URLs available",
        }

    # Pad to 4 if fewer
    while len(valid_urls) < 4:
        valid_urls.append(valid_urls[-1])

    message = generate_whatsapp_message(
        business_name=lead.get("business_name", "Ihr Betrieb"),
        owner_name=lead.get("owner_name", ""),
        url1=valid_urls[0],
        url2=valid_urls[1],
        url3=valid_urls[2],
        url4=valid_urls[3],
        sender_name=sender_name,
        variant=variant,
    )

    wa_link = generate_wa_me_link(formatted_phone, message)

    return {
        "business_name": lead.get("business_name", "?"),
        "phone": phone_raw,
        "formatted_phone": formatted_phone,
        "message": message,
        "wa_me_link": wa_link,
        "variant": variant,
    }


def batch_generate(
    leads: list[dict],
    sender_name: str,
    variant: str = "day0",
) -> list[dict]:
    """Generate WhatsApp links for multiple leads."""
    results = []
    for lead in leads:
        result = generate_for_lead(lead, sender_name, variant)
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate WhatsApp outreach links for leads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--phone", help="Phone number (single lead mode)")
    parser.add_argument("--business-name", help="Business name")
    parser.add_argument("--owner-name", default="", help="Owner name for greeting")
    parser.add_argument("--url-1", help="Draft website URL 1")
    parser.add_argument("--url-2", help="Draft website URL 2")
    parser.add_argument("--url-3", help="Draft website URL 3")
    parser.add_argument("--url-4", help="Draft website URL 4")
    parser.add_argument("--sender-name", required=True, help="Your name")
    parser.add_argument("--variant", default="day0", choices=["day0", "post_call", "followup"])
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.phone:
        print("ERROR: --phone is required for single lead mode")
        sys.exit(1)

    formatted = format_swiss_phone(args.phone)
    if not formatted:
        print(f"ERROR: Could not parse phone number: {args.phone}")
        sys.exit(1)

    message = generate_whatsapp_message(
        business_name=args.business_name or "Ihr Betrieb",
        owner_name=args.owner_name,
        url1=args.url_1 or "",
        url2=args.url_2 or "",
        url3=args.url_3 or "",
        url4=args.url_4 or "",
        sender_name=args.sender_name,
        variant=args.variant,
    )

    wa_link = generate_wa_me_link(formatted, message)

    if args.json:
        print(json.dumps({
            "phone": args.phone,
            "formatted_phone": formatted,
            "message": message,
            "wa_me_link": wa_link,
            "variant": args.variant,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"\n{'='*60}")
        print(f"WhatsApp an: {args.business_name or '?'} ({args.phone})")
        print(f"{'='*60}")
        print(f"\nNachricht:\n{message}")
        print(f"\nKlicken Sie hier zum Senden:")
        print(f"  {wa_link}")
        print()


if __name__ == "__main__":
    main()
