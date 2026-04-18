#!/usr/bin/env python3
"""
Generate a German phone call cheat sheet for cold outreach.

Produces a word-for-word call script designed for someone who is new to
sales calls. Includes exact phrases, a decision tree, objection handling,
confidence builders, and a ready-to-send WhatsApp template.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate

# Import WhatsApp link generation
WHATSAPP_SCRIPT = PROJECT_ROOT / ".claude" / "skills" / "whatsapp-outreach" / "scripts"
sys.path.insert(0, str(WHATSAPP_SCRIPT))
from send_whatsapp import format_swiss_phone, generate_whatsapp_message, generate_wa_me_link


def generate_call_script(
    business_name: str,
    category: str,
    city: str,
    phone: str,
    owner_name: str | None,
    url1: str,
    url2: str,
    url3: str,
    url4: str = "",
    sender_name: str = "",
    email_sent: bool = False,
    whatsapp_sent: bool = False,
    address: str = "",
    rating: str = "",
    review_count: str = "",
) -> dict:
    """Generate the full call cheat sheet with word-for-word scripts."""

    contact_name = owner_name if owner_name and owner_name.strip() else "den Inhaber / die Inhaberin"
    greeting_name = owner_name.strip() if owner_name and owner_name.strip() else ""
    greeting = f" {greeting_name}" if greeting_name else ""

    # --- Confidence Builder ---
    confidence = f"""
{'='*60}
  BEVOR SIE ANRUFEN — KURZ DURCHATMEN
{'='*60}

  Sie bieten etwas GRATIS an. Die Webseiten sind schon fertig.
  Sie verschenken etwas Wertvolles — kein Verkaufsgespräch nötig.

  Das Schlimmste, was passieren kann: "Nein danke."
  Das ist völlig okay. Weiter zum nächsten.

  Ziel des Anrufs: Nur die Links per WhatsApp schicken dürfen.
  Mehr nicht. Kein Verkauf am Telefon.

  Atmen Sie einmal tief durch. Dann wählen Sie.
"""

    # --- Info Card ---
    info_card = f"""
{'─'*60}
  BETRIEB: {business_name}
  BRANCHE: {category or '(nicht bekannt)'}     ORT: {city}
  TELEFON: {phone}
  {f'ADRESSE: {address}' if address else ''}
  {f'GOOGLE:  {rating} Sterne ({review_count} Bewertungen)' if rating else ''}
  KONTAKT: {contact_name}
  {'WhatsApp gesendet: Ja' if whatsapp_sent else ''}{'E-Mail gesendet: Ja' if email_sent else ''}
{'─'*60}
"""

    # --- Opening (3 variants) ---
    if whatsapp_sent:
        opening = f"""
ERÖFFNUNG (WhatsApp wurde gesendet):
{'─'*45}

SIE: "Grüezi{greeting}, mein Name ist {sender_name}.
      Ich habe Ihnen vor ein paar Tagen eine WhatsApp-Nachricht
      geschickt mit Website-Entwürfen für {business_name} —
      haben Sie die gesehen?"

      ... PAUSE — warten bis sie antworten ...

  Falls JA ("Ja, habe ich gesehen"):
  ──────────────────────────────────
  SIE: "Super! Und — hat Ihnen eines der Designs gefallen?"

    → Falls ein Design gefällt:
      SIE: "Das freut mich! Wir können das Design genau an
           Ihren Betrieb anpassen — Ihre Farben, Texte, Fotos.
           Soll ich Ihnen dazu kurz eine Nachricht schicken?"

    → Falls kein Design gefällt:
      SIE: "Kein Problem! Was hätten Sie sich denn vorgestellt?
           Wir passen das gerne komplett an."

  Falls NEIN ("Nein, habe ich nicht gesehen"):
  ─────────────────────────────────────────────
  SIE: "Kein Problem! Ich schicke Ihnen die Links gleich nochmal.
       Wir haben 4 verschiedene Designs erstellt, speziell für
       {business_name}. Kostenlos und unverbindlich — schauen
       Sie einfach mal rein, wenn Sie 2 Minuten haben."
"""

    elif email_sent:
        opening = f"""
ERÖFFNUNG (E-Mail wurde gesendet):
{'─'*45}

SIE: "Grüezi{greeting}, mein Name ist {sender_name}.
      Ich habe Ihnen vor ein paar Tagen eine E-Mail geschickt
      mit Website-Entwürfen für {business_name} — haben Sie
      die gesehen?"

      ... PAUSE — warten bis sie antworten ...

  Falls JA:
  SIE: "Super! Welches Design hat Ihnen am besten gefallen?"

  Falls NEIN:
  SIE: "Kein Problem! Darf ich Ihnen die Links per WhatsApp
       schicken? Dann sehen Sie die sofort."
"""

    else:
        opening = f"""
ERÖFFNUNG (Erstkontakt — kein WhatsApp/E-Mail vorher):
{'─'*45}

SIE: "Grüezi{greeting}, mein Name ist {sender_name}.
      Ich rufe an weil ich gesehen habe, dass {business_name}
      in {city} noch keine eigene Webseite hat."

      ... KURZE PAUSE — lassen Sie sie reagieren ...

SIE: "Deshalb habe ich mir erlaubt, 4 Website-Entwürfe
      für Ihren Betrieb zu erstellen. Komplett kostenlos
      und unverbindlich — darf ich Ihnen die Links per
      WhatsApp schicken?"
"""

    # --- Rating hook (optional) ---
    rating_hook = ""
    if rating and review_count:
        rating_hook = f"""
OPTIONAL — Wenn sich das Gespräch natürlich ergibt:
{'─'*45}

SIE: "Ich habe übrigens gesehen, dass Sie auf Google {rating}
      Sterne haben mit {review_count} Bewertungen — Ihre Kunden
      sind offensichtlich sehr zufrieden! Mit einer eigenen
      Webseite könnten noch mehr Leute Sie finden."
"""

    # --- Conversation Flow (word-for-word) ---
    flow = f"""
GESPRÄCHSVERLAUF:
{'─'*45}

Reaktion POSITIV ("Ja, schicken Sie mal"):
  SIE: "Toll! Ich schicke Ihnen gleich 4 verschiedene Designs per
       WhatsApp. Schauen Sie sich die in Ruhe an — es gibt Klassisch,
       Modern, Frisch und Elegant. Welches Ihnen gefällt, können wir
       dann genau anpassen."
  SIE: "Passt es, wenn ich Ende der Woche nochmal kurz anrufe?"

Reaktion NEUTRAL ("Ich habe eigentlich keine Zeit"):
  SIE: "Verstehe ich total. Deshalb habe ich die Webseiten schon
       fertig erstellt — Sie müssen gar nichts machen. Ich schicke
       Ihnen einfach die Links per WhatsApp, dann können Sie
       reinschauen, wenn Sie mal 2 Minuten haben."

Reaktion NEGATIV ("Kein Interesse"):
  SIE: "Kein Problem! Die Entwürfe bleiben noch ein paar Wochen
       online, falls Sie es sich anders überlegen. Ich wünsche
       Ihnen einen schönen Tag!"
  → Freundlich verabschieden. NICHT drängen.
"""

    # --- Objection Handling (word-for-word) ---
    cat_text = category or "Betrieb"
    objections = f"""
EINWÄNDE — Was sie sagen könnten:
{'─'*45}

"WAS KOSTET DAS?"
  SIE: "Die Entwürfe sind komplett kostenlos. Wenn Sie sich für
       ein Design entscheiden und wir es fertigstellen, kostet
       das einmalig ab CHF 490. Aber schauen Sie sich erstmal
       die Entwürfe an — ganz unverbindlich."

"ICH BRAUCHE KEINE WEBSITE"
  SIE: "Verstehe ich. Aber wussten Sie, dass heute über 80% der
       Kunden online nach einem {cat_text} in {city} suchen?
       Ohne Webseite finden die leider nur Ihre Konkurrenz.
       Die Entwürfe sind kostenlos — schauen Sie einfach mal rein."

"ICH HABE SCHON JEMANDEN"
  SIE: "Super, dann sind Sie gut aufgestellt! Falls es mal nicht
       klappt, denken Sie an uns. Ich wünsche Ihnen alles Gute!"
  → Freundlich verabschieden.

"SCHICKEN SIE MIR EINE E-MAIL"
  SIE: "Mache ich gerne! An welche E-Mail-Adresse darf ich
       schreiben?"
  → E-Mail-Adresse SOFORT notieren!
  → Im Google Sheet eintragen (owner_email).

"ICH MUSS DAS MIT MEINEM PARTNER BESPRECHEN"
  SIE: "Natürlich! Ich schicke Ihnen die Links per WhatsApp,
       dann können Sie die zusammen anschauen. Passt es, wenn
       ich nächste Woche nochmal kurz anrufe?"
"""

    # --- WhatsApp template + wa.me link ---
    urls = [u for u in [url1, url2, url3, url4] if u]
    while len(urls) < 4:
        urls.append(urls[-1] if urls else "")

    formatted_phone = format_swiss_phone(phone)
    wa_message = generate_whatsapp_message(
        business_name=business_name,
        owner_name=owner_name,
        url1=urls[0],
        url2=urls[1],
        url3=urls[2],
        url4=urls[3],
        sender_name=sender_name,
        variant="post_call",
    )

    wa_link = generate_wa_me_link(formatted_phone, wa_message) if formatted_phone else "(Telefonnummer nicht erkannt)"

    whatsapp_section = f"""
NACH DEM ANRUF — WHATSAPP SENDEN:
{'─'*45}

Klicken Sie diesen Link — WhatsApp öffnet sich mit der Nachricht:

  {wa_link}

Oder Text zum Kopieren:
{wa_message}
"""

    # --- Close ---
    close = f"""
ABSCHLUSS:
{'─'*45}

Immer freundlich:
  SIE: "Vielen Dank für Ihre Zeit!"
  SIE: "Ich wünsche Ihnen einen schönen Tag."
  SIE: "Falls Fragen auftauchen — meine Nummer haben Sie ja."

NACH DEM ANRUF:
  1. WhatsApp mit Links senden (Link oben klicken)
  2. Google Sheet aktualisieren: Status + Notizen
  3. Nächsten Anruf planen (oder nächsten Lead)
"""

    full_script = confidence + info_card + opening + rating_hook + flow + objections + whatsapp_section + close

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
        "whatsapp_sent": whatsapp_sent,
        "sender_name": sender_name,
        "website_urls": urls,
        "wa_me_link": wa_link,
        "script_text": full_script,
        "sms_template": wa_message,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a call script for cold outreach")
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--category", default="")
    parser.add_argument("--city", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--owner-name", default="")
    parser.add_argument("--website-url-1", required=True)
    parser.add_argument("--website-url-2", required=True)
    parser.add_argument("--website-url-3", required=True)
    parser.add_argument("--website-url-4", default="")
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--email-sent", action="store_true", help="Set if email was already sent")
    parser.add_argument("--whatsapp-sent", action="store_true", help="Set if WhatsApp was already sent")
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
        url4=args.website_url_4,
        sender_name=args.sender_name,
        email_sent=args.email_sent,
        whatsapp_sent=args.whatsapp_sent,
        address=args.address,
        rating=args.rating,
        review_count=args.review_count,
    )

    print(result["script_text"])

    output_path = save_intermediate(result, "call_script")
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
