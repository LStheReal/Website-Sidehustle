#!/usr/bin/env python3
"""
General-purpose German email writer for all pipeline stages.

Generates contextual emails based on the current stage:
- onboarding: request values, logo, images, domain preference
- status_update: progress on website build
- domain_confirm: confirm domain choice before purchase
- delivery: final website is live
- invoice: payment request
- support: general follow-up
- custom: free-form based on --context
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.utils import save_intermediate


STAGES = ["onboarding", "status_update", "domain_confirm", "delivery", "invoice", "support", "custom"]


def greeting(owner_name: str | None) -> str:
    if owner_name and owner_name.strip():
        return f"Grüezi {owner_name}"
    return "Grüezi"


def sign_off(sender_name: str, sender_phone: str, sender_email: str) -> str:
    return f"""Freundliche Grüsse
{sender_name}
{sender_phone}
{sender_email}"""


# --- Email generators per stage ---

def email_onboarding(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, **kw):
    g = greeting(owner_name)
    subject = f"Nächste Schritte — Website für {business_name}"
    body = f"""{g}

Vielen Dank für Ihr Interesse an der Website für {business_name}! Damit ich die Seite genau auf Sie anpassen kann, brauche ich noch ein paar Informationen:

1. Welches der 3 Designs gefällt Ihnen am besten? (Falls noch nicht mitgeteilt)
2. Was sind die wichtigsten Werte / Stärken von {business_name}? (2-3 kurze Sätze reichen)
3. Haben Sie ein Logo? (Falls ja, einfach als Anhang mitschicken)
4. Haben Sie Fotos von Ihrem Betrieb oder Team? (Optional, aber empfohlen)
5. Welchen Domain-Namen bevorzugen Sie? (Ich schlage Ihnen Optionen vor)

Antworten Sie einfach auf diese E-Mail — es muss nicht perfekt sein. Ich kümmere mich um den Rest!

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "onboarding"}


def email_status_update(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, **kw):
    g = greeting(owner_name)
    detail = context if context else "Die Anpassungen laufen und die Seite sieht bereits sehr gut aus."
    subject = f"Update — Website {business_name}"
    body = f"""{g}

Kurzes Update zu Ihrer Website für {business_name}:

{detail}

Ich melde mich, sobald alles fertig ist. Falls Sie in der Zwischenzeit Fragen haben, rufen Sie mich gerne an.

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "status_update"}


def email_domain_confirm(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, domain="", **kw):
    g = greeting(owner_name)
    domain_text = f"**{domain}**" if domain else "[Domain-Name]"
    subject = f"Domain bestätigen — {business_name}"
    body = f"""{g}

Die Website für {business_name} ist fast fertig! Bevor ich die Domain registriere, möchte ich kurz bestätigen:

Domain: {domain_text}

Die Domain kostet ca. 10-15 CHF pro Jahr. Soll ich diese für Sie reservieren?

Antworten Sie einfach mit "Ja" — dann registriere ich die Domain und schalte Ihre Website live.

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "domain_confirm"}


def email_delivery(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, website_url="", domain="", **kw):
    g = greeting(owner_name)
    url_text = website_url if website_url else "[URL]"
    subject = f"Ihre Website ist live — {business_name}"
    body = f"""{g}

Ihre Website für {business_name} ist jetzt online!

Hier ist der Link: {url_text}

Die Seite ist bereits für Suchmaschinen optimiert und sieht auf allen Geräten (Handy, Tablet, Desktop) professionell aus.

Falls Sie noch Änderungen wünschen, lassen Sie es mich wissen — kleine Anpassungen sind jederzeit möglich.

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "delivery"}


def email_invoice(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, price="", website_url="", **kw):
    g = greeting(owner_name)
    price_text = price if price else "[Betrag]"
    subject = f"Rechnung — Website {business_name}"
    body = f"""{g}

Vielen Dank, dass Sie sich für eine professionelle Website entschieden haben!

Anbei die Rechnung für die Website von {business_name}:

Betrag: CHF {price_text}
Leistung: Website-Erstellung, Domain-Registrierung, Hosting (1 Jahr)

Zahlbar innert 30 Tagen.

Bei Fragen zur Rechnung stehe ich Ihnen gerne zur Verfügung.

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "invoice"}


def email_support(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, **kw):
    g = greeting(owner_name)
    detail = context if context else "Ich wollte kurz nachfragen, ob alles mit Ihrer Website in Ordnung ist."
    subject = f"Nachfrage — Website {business_name}"
    body = f"""{g}

{detail}

Falls Sie Änderungen an der Website wünschen oder Fragen haben, melden Sie sich jederzeit bei mir.

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "support"}


def email_custom(business_name, owner_name, city, sender_name, sender_phone, sender_email, context, **kw):
    g = greeting(owner_name)
    if not context:
        context = "Ich wollte mich kurz bei Ihnen melden."
    subject = f"{business_name} — Nachricht"
    body = f"""{g}

{context}

{sign_off(sender_name, sender_phone, sender_email)}"""
    return {"subject": subject, "body": body, "stage": "custom"}


GENERATORS = {
    "onboarding": email_onboarding,
    "status_update": email_status_update,
    "domain_confirm": email_domain_confirm,
    "delivery": email_delivery,
    "invoice": email_invoice,
    "support": email_support,
    "custom": email_custom,
}


def main():
    parser = argparse.ArgumentParser(description="Generate contextual German emails for any pipeline stage")
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--owner-name", default="")
    parser.add_argument("--city", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES, help="Pipeline stage")
    parser.add_argument("--sender-name", required=True)
    parser.add_argument("--sender-phone", required=True)
    parser.add_argument("--sender-email", required=True)
    parser.add_argument("--context", default="", help="Additional context for email content")
    parser.add_argument("--website-url", default="", help="Live website URL")
    parser.add_argument("--domain", default="", help="Domain name")
    parser.add_argument("--price", default="", help="Price for invoice emails")
    args = parser.parse_args()

    generator = GENERATORS[args.stage]
    email = generator(
        business_name=args.business_name,
        owner_name=args.owner_name,
        city=args.city,
        sender_name=args.sender_name,
        sender_phone=args.sender_phone,
        sender_email=args.sender_email,
        context=args.context,
        website_url=args.website_url,
        domain=args.domain,
        price=args.price,
    )

    # Save
    result = {
        "generated_at": datetime.now().isoformat(),
        "recipient": {
            "business_name": args.business_name,
            "owner_name": args.owner_name,
            "city": args.city,
        },
        "sender": {
            "name": args.sender_name,
            "phone": args.sender_phone,
            "email": args.sender_email,
        },
        "email": email,
        "context": args.context,
    }
    output_path = save_intermediate(result, "email")

    # Print
    print(f"\n{'='*60}")
    print(f"  Stage: {email['stage'].upper()}")
    print(f"{'='*60}")
    print(f"  Betreff: {email['subject']}")
    print(f"{'─'*60}")
    print(email["body"])
    print(f"\nSaved to: {output_path}")

    # JSON
    print(f"\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
