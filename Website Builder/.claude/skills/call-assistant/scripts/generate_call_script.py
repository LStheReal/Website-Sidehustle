#!/usr/bin/env python3
"""
Generate a German phone call cheat sheet for cold outreach.

Produces a structured call script with:
- Business info card (facts at a glance)
- Opening lines (with/without prior email)
- Conversation flow with branches
- Objection handling in German
- SMS/WhatsApp template with links
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate


def generate_call_script(
    business_name: str,
    category: str,
    city: str,
    phone: str,
    owner_name: str | None,
    url1: str,
    url2: str,
    url3: str,
    sender_name: str,
    email_sent: bool = False,
    address: str = "",
    rating: str = "",
    review_count: str = "",
) -> dict:
    """Generate the full call cheat sheet."""

    contact_name = owner_name if owner_name and owner_name.strip() else "den Inhaber / die Inhaberin"
    greeting_name = owner_name if owner_name and owner_name.strip() else ""

    # --- Info Card ---
    info_card = f"""
┌─────────────────────────────────────────────┐
│  {business_name}
│  {category} — {city}
│  Tel: {phone}
│  {f'Adresse: {address}' if address else ''}
│  {f'Google: {rating}★ ({review_count} Bewertungen)' if rating else ''}
│  Kontakt: {contact_name}
│  E-Mail gesendet: {'Ja' if email_sent else 'Nein'}
└─────────────────────────────────────────────┘"""

    # --- Opening ---
    if email_sent:
        opening = f"""
ERÖFFNUNG (E-Mail wurde gesendet):
───────────────────────────────────
"Grüezi{f' {greeting_name}' if greeting_name else ''}, mein Name ist {sender_name}.

Ich habe Ihnen vor ein paar Tagen eine E-Mail mit 3 Website-Entwürfen
für {business_name} geschickt — haben Sie die gesehen?"

→ Falls JA:  "Super! Welches Design hat Ihnen am besten gefallen?"
→ Falls NEIN: "Kein Problem! Darf ich Ihnen die Links kurz per
              SMS oder WhatsApp schicken? Dauert nur 2 Sekunden."
"""
    else:
        opening = f"""
ERÖFFNUNG (Kein E-Mail — Erstkontakt per Telefon):
───────────────────────────────────────────────────
"Grüezi{f' {greeting_name}' if greeting_name else ''}, mein Name ist {sender_name}.

Ich habe gesehen, dass {business_name} in {city} noch keine eigene
Website hat. Deshalb habe ich 3 Website-Entwürfe für Sie erstellt —
komplett kostenlos und unverbindlich.

Darf ich Ihnen die Links per SMS oder WhatsApp schicken,
damit Sie sich die Designs anschauen können?"
"""

    # --- Conversation Flow ---
    flow = """
GESPRÄCHSVERLAUF:
─────────────────
Reaktion positiv ("Ja, schicken Sie mal"):
  → "Toll, ich schicke Ihnen gleich die 3 Links."
  → "Schauen Sie sich die Entwürfe in Ruhe an."
  → "Welches Design Ihnen gefällt, passen wir dann genau an."
  → "Darf ich Sie Ende der Woche nochmal anrufen?"

Reaktion neutral ("Ich habe eigentlich keine Zeit"):
  → "Verstehe ich total. Deshalb habe ich die Website schon
     fertig erstellt — Sie müssen nichts machen."
  → "Schauen Sie einfach kurz rein, wenn Sie 2 Minuten haben."
  → SMS/WhatsApp mit Links schicken.

Reaktion negativ ("Kein Interesse"):
  → "Kein Problem! Die Entwürfe bleiben noch eine Weile online,
     falls Sie es sich anders überlegen."
  → "Darf ich fragen — haben Sie eine Website bei einem
     anderen Anbieter geplant?"
  → Freundlich verabschieden, nicht drängen.
"""

    # --- Objection Handling ---
    objections = """
EINWÄNDE BEHANDELN:
───────────────────
"Was kostet das?"
  → "Die Entwürfe sind kostenlos. Wenn Sie sich für ein Design
     entscheiden, kostet die fertige Website CHF [PREIS] einmalig
     plus CHF [PREIS]/Jahr für Hosting und Domain."

"Ich brauche keine Website"
  → "Viele Ihrer Kunden suchen heute online nach einem
     {category}-Betrieb in {city}. Ohne Website finden die
     Sie leider nicht — aber Ihre Konkurrenz schon."

"Ich habe schon jemanden"
  → "Super, dann sind Sie gut aufgestellt! Falls es nicht
     klappt, melden Sie sich gerne bei mir."

"Schicken Sie mir eine E-Mail"
  → "Mache ich gerne! An welche Adresse darf ich schreiben?"
  → (E-Mail-Adresse notieren → cold-email Skill nutzen)

"Ich muss das mit meinem Partner besprechen"
  → "Natürlich! Ich schicke Ihnen die Links, dann können
     Sie die zusammen anschauen. Passt es, wenn ich
     nächste Woche nochmal anrufe?"
"""

    # --- SMS Template ---
    sms_template = f"""
SMS / WHATSAPP NACHRICHT (zum Kopieren):
────────────────────────────────────────
Grüezi{f' {greeting_name}' if greeting_name else ''}, hier ist {sender_name}. Wie besprochen, hier die 3 Website-Entwürfe für {business_name}:

1) Klassisch: {url1}
2) Modern: {url2}
3) Frisch: {url3}

Welches Design gefällt Ihnen? Einfach antworten oder anrufen!
"""

    # --- Close ---
    close = """
ABSCHLUSS:
──────────
Immer freundlich abschliessen:
  → "Vielen Dank für Ihre Zeit!"
  → "Ich wünsche Ihnen einen schönen Tag."
  → "Falls Fragen auftauchen, rufen Sie mich jederzeit an."

NACH DEM ANRUF:
  → SMS/WhatsApp mit Links schicken (falls vereinbart)
  → Google Sheet updaten: status, notes
  → Nächsten Anruf / Follow-up planen
"""

    full_script = info_card + opening + flow + objections.replace("{category}", category).replace("{city}", city) + sms_template + close

    return {
        "generated_at": datetime.now().isoformat(),
        "business": {
            "name": business_name,
            "category": category,
            "city": city,
            "phone": phone,
            "owner_name": owner_name or "",
            "address": address,
            "rating": rating,
            "review_count": review_count,
        },
        "email_sent": email_sent,
        "sender_name": sender_name,
        "website_urls": [url1, url2, url3],
        "script_text": full_script,
        "sms_template": sms_template.strip(),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a call script for cold outreach")
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--owner-name", default="")
    parser.add_argument("--website-url-1", required=True)
    parser.add_argument("--website-url-2", required=True)
    parser.add_argument("--website-url-3", required=True)
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--email-sent", action="store_true", help="Set if cold email was already sent")
    parser.add_argument("--address", default="")
    parser.add_argument("--rating", default="")
    parser.add_argument("--review-count", default="")
    args = parser.parse_args()

    result = generate_call_script(
        business_name=args.business_name,
        category=args.category,
        city=args.city,
        phone=args.phone,
        owner_name=args.owner_name,
        url1=args.website_url_1,
        url2=args.website_url_2,
        url3=args.website_url_3,
        sender_name=args.sender_name,
        email_sent=args.email_sent,
        address=args.address,
        rating=args.rating,
        review_count=args.review_count,
    )

    # Print the script
    print(result["script_text"])

    # Save to .tmp
    output_path = save_intermediate(result, "call_script")
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
