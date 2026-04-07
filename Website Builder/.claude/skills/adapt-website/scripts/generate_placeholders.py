#!/usr/bin/env python3
"""
Generate all placeholder values for a website template using the Anthropic API (Sonnet).

This script calls the Claude API directly with a focused prompt (~2k tokens),
avoiding the need to send the full conversation context. Much cheaper than
generating placeholders through the main Claude Code conversation.

Usage:
    python3 generate_placeholders.py \
        --template-key bia \
        --business-name "Diamant Falke" \
        --category "Nagelstudio" \
        --city "Luzern" \
        --phone "+41 41 123 45 67" \
        --email "info@example.com" \
        --address "Bahnhofstrasse 1, 6003 Luzern" \
        --description "Exklusives Nagelstudio für Gel-Nägel, Maniküre und Pediküre" \
        --values "15 Jahre Erfahrung, 500 zufriedene Kundinnen, Gel-Nägel, Shellac, Nail Art" \
        --output .tmp/business_data.json
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (4 levels up from scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Placeholder lists per template
TEMPLATE_PLACEHOLDERS = {
    "earlydog": [
        "BUSINESS_NAME", "TAGLINE", "META_DESCRIPTION",
        "HERO_TITLE_LINE1", "HERO_TITLE_LINE2", "HERO_DESCRIPTION",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION", "SERVICE_1_CTA",
        "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION", "SERVICE_2_CTA",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICE_3_CTA",
        "CTA_TITLE_LINE1", "CTA_TITLE_LINE2",
        "PHONE", "EMAIL", "ADDRESS",
    ],
    "bia": [
        "BUSINESS_NAME", "BUSINESS_NAME_SHORT", "TAGLINE", "META_DESCRIPTION",
        "SECTION_LABEL_HERO", "HERO_TITLE_LINE1", "HERO_TITLE_LINE2", "HERO_TITLE_LINE3",
        "INTRO_TEXT", "INTRO_DESCRIPTION",
        "SECTION_LABEL_SERVICES", "SERVICES_HEADING",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION",
        "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION",
        "SERVICE_4_TITLE", "SERVICE_4_DESCRIPTION",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING", "ABOUT_DESCRIPTION",
        "STAT_1_NUMBER", "STAT_1_LABEL", "STAT_2_NUMBER", "STAT_2_LABEL",
        "STAT_3_NUMBER", "STAT_3_LABEL",
        "CTA_TITLE_LINE1", "CTA_TITLE_LINE2", "CTA_TITLE_LINE3",
        "PHONE", "EMAIL", "ADDRESS", "OPENING_HOURS",
    ],
    "liveblocks": [
        "BUSINESS_NAME", "BUSINESS_NAME_SHORT", "TAGLINE", "META_DESCRIPTION",
        "SECTION_LABEL_HERO", "HERO_TITLE_LINE1", "HERO_TITLE_LINE2",
        "HERO_WORD_1", "HERO_WORD_2", "HERO_WORD_3", "HERO_WORD_4", "HERO_DESCRIPTION",
        "CTA_BUTTON_PRIMARY", "CTA_BUTTON_SECONDARY", "TRUST_LABEL",
        "STAT_1_NUMBER", "STAT_1_LABEL", "STAT_2_NUMBER", "STAT_2_LABEL",
        "STAT_3_NUMBER", "STAT_3_LABEL", "STAT_4_NUMBER", "STAT_4_LABEL",
        "SECTION_LABEL_SERVICES", "SERVICES_HEADING", "SERVICES_DESCRIPTION",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION", "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION", "SERVICE_4_TITLE", "SERVICE_4_DESCRIPTION",
        "SERVICE_5_TITLE", "SERVICE_5_DESCRIPTION", "SERVICE_6_TITLE", "SERVICE_6_DESCRIPTION",
        "SECTION_LABEL_FEATURE", "FEATURE_HEADING", "FEATURE_DESCRIPTION",
        "FEATURE_POINT_1", "FEATURE_POINT_2", "FEATURE_POINT_3",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING", "ABOUT_LEAD", "ABOUT_DESCRIPTION",
        "VALUE_1_TITLE", "VALUE_1_DESCRIPTION", "VALUE_2_TITLE", "VALUE_2_DESCRIPTION",
        "VALUE_3_TITLE", "VALUE_3_DESCRIPTION",
        "CTA_HEADING_LINE1", "CTA_HEADING_LINE2", "CTA_DESCRIPTION",
        "CONTACT_CARD_1_TITLE", "CONTACT_CARD_1_DESCRIPTION",
        "CONTACT_CARD_2_TITLE", "CONTACT_CARD_2_DESCRIPTION",
        "PHONE", "PHONE_SHORT", "EMAIL", "ADDRESS", "OPENING_HOURS",
        "FOOTER_COL_1_TITLE", "FOOTER_COL_1_LINK_1", "FOOTER_COL_1_LINK_2", "FOOTER_COL_1_LINK_3",
        "FOOTER_COL_2_TITLE", "FOOTER_COL_2_LINK_1", "FOOTER_COL_2_LINK_2", "FOOTER_COL_2_LINK_3",
    ],
    "loveseen": [
        "BUSINESS_NAME", "TAGLINE", "META_DESCRIPTION",
        "NAV_CTA", "NAV_LINK_1", "NAV_LINK_2", "NAV_LINK_3", "NAV_LINK_4",
        "HERO_TITLE_LINE1", "HERO_TITLE_LINE2", "HERO_CTA",
        "SECTION_LABEL_ABOUT", "ABOUT_HEADING_LINE1", "ABOUT_HEADING_LINE2",
        "ABOUT_LEAD", "ABOUT_DESCRIPTION", "ABOUT_CTA",
        "STATEMENT_LABEL", "STATEMENT_LINE1", "STATEMENT_LINE2", "STATEMENT_LINE3",
        "SECTION_LABEL_SERVICES", "SERVICES_HEADING",
        "SERVICE_1_TITLE", "SERVICE_1_DESCRIPTION",
        "SERVICE_2_TITLE", "SERVICE_2_DESCRIPTION",
        "SERVICE_3_TITLE", "SERVICE_3_DESCRIPTION",
        "SERVICES_CTA", "GALLERY_LABEL", "INSTAGRAM_HANDLE", "INSTAGRAM_URL",
        "CONTACT_TAGLINE", "EMAIL_PLACEHOLDER",
        "CONTACT_LABEL_PHONE", "CONTACT_LABEL_EMAIL", "CONTACT_LABEL_ADDRESS", "CONTACT_LABEL_HOURS",
        "PHONE", "EMAIL", "ADDRESS", "OPENING_HOURS",
        "FOOTER_PRIVACY", "FOOTER_TERMS", "FOOTER_YEAR",
    ],
}


def build_prompt(template_key: str, business_name: str, category: str, city: str,
                 phone: str, email: str, address: str, description: str, values: str,
                 opening_hours: str = "") -> str:
    """Build a focused prompt for placeholder generation."""
    placeholders = TEMPLATE_PLACEHOLDERS.get(template_key, [])

    # Separate fixed values from AI-generated ones
    fixed_keys = {"PHONE", "PHONE_SHORT", "EMAIL", "ADDRESS", "OPENING_HOURS",
                  "BUSINESS_NAME", "FOOTER_YEAR", "FOOTER_PRIVACY", "FOOTER_TERMS"}
    ai_keys = [k for k in placeholders if k not in fixed_keys]

    return f"""Du bist ein Website-Texter für Schweizer KMU. Generiere professionellen Website-Text auf Deutsch (Hochdeutsch, Schweizer Markt) für dieses Unternehmen.

UNTERNEHMEN:
- Name: {business_name}
- Branche: {category}
- Stadt: {city}
- Beschreibung: {description}
- Stärken/Werte: {values}

REGELN:
- Alle Texte auf Deutsch (Hochdeutsch, nicht Dialekt)
- Ton an Branche anpassen (Anwalt = formell, Coiffeur = freundlich, IT = modern)
- HERO_TITLE Zeilen: max 3-4 Wörter, wie ein Plakat — kurz und einprägsam
- BUSINESS_NAME_SHORT: Erstes sinnvolles Wort + Punkt (z.B. "Diamant.", "Weber.")
- STAT Nummern: Format "15+", "500+", "100%" — aus den Stärken/Werten ableiten
- SERVICE Titel: spezifisch zur Branche (nicht generisch "Beratung", "Umsetzung")
- SERVICE Beschreibungen: 1-2 Sätze
- CTA Buttons: branchengerecht ("Termin vereinbaren", "Offerte anfordern", "Kontakt aufnehmen")
- SECTION_LABEL: 2-3 Wörter
- META_DESCRIPTION: max 155 Zeichen, SEO-optimiert
- Keine Fakten erfinden — nur aus der Beschreibung und den Werten ableiten

Generiere ein JSON-Objekt mit diesen Schlüsseln:
{json.dumps(ai_keys, ensure_ascii=False)}

Antworte NUR mit dem JSON-Objekt, kein anderer Text."""


def generate_placeholders(template_key: str, business_name: str, category: str, city: str,
                          phone: str, email: str, address: str, description: str, values: str,
                          opening_hours: str = "", model: str = "claude-sonnet-4-20250514") -> dict:
    """Call the Anthropic API to generate all placeholder values."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    prompt = build_prompt(template_key, business_name, category, city,
                          phone, email, address, description, values, opening_hours)

    print(f"Generating {len(TEMPLATE_PLACEHOLDERS.get(template_key, []))} placeholders for {template_key} template...")
    print(f"  Model: {model}")
    print(f"  Business: {business_name} ({category}, {city})")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": model,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        print(f"ERROR: API call failed: {e}", file=sys.stderr)
        sys.exit(1)

    text = "".join(b.get("text", "") for b in result.get("content", []))

    # Extract JSON from response
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        print(f"ERROR: No JSON found in API response", file=sys.stderr)
        print(f"Response: {text[:500]}", file=sys.stderr)
        sys.exit(1)

    ai_data = json.loads(match.group(0))

    # Add fixed values
    ai_data["BUSINESS_NAME"] = business_name
    ai_data["PHONE"] = phone
    ai_data["EMAIL"] = email
    ai_data["ADDRESS"] = address
    ai_data["OPENING_HOURS"] = opening_hours or "Mo-Fr 8:00-18:00"
    ai_data["FOOTER_YEAR"] = str(__import__("datetime").datetime.now().year)
    ai_data["FOOTER_PRIVACY"] = "Datenschutz"
    ai_data["FOOTER_TERMS"] = "AGB"

    if "PHONE_SHORT" not in ai_data and phone:
        # Strip country code for short version
        short = phone.replace("+41 ", "0").replace("+41", "0")
        ai_data["PHONE_SHORT"] = short

    # Validate — check all required placeholders are present
    expected = set(TEMPLATE_PLACEHOLDERS.get(template_key, []))
    missing = expected - set(ai_data.keys())
    if missing:
        print(f"  WARNING: {len(missing)} missing placeholders: {', '.join(sorted(missing))}")
    else:
        print(f"  All {len(expected)} placeholders generated successfully")

    # Report token usage
    usage = result.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    print(f"  Tokens: {input_tokens} in / {output_tokens} out")

    return ai_data


def main():
    parser = argparse.ArgumentParser(description="Generate website placeholder content via Sonnet API")
    parser.add_argument("--template-key", required=True, choices=list(TEMPLATE_PLACEHOLDERS.keys()),
                        help="Template to generate for")
    parser.add_argument("--business-name", required=True, help="Business name")
    parser.add_argument("--category", default="", help="Business category")
    parser.add_argument("--city", default="", help="City")
    parser.add_argument("--phone", default="", help="Phone number")
    parser.add_argument("--email", default="", help="Email address")
    parser.add_argument("--address", default="", help="Full address")
    parser.add_argument("--description", default="", help="Business description from customer")
    parser.add_argument("--values", default="", help="Customer values/highlights (comma-separated)")
    parser.add_argument("--opening-hours", default="", help="Opening hours")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Anthropic model to use")
    parser.add_argument("--output", default=".tmp/business_data.json", help="Output JSON file path")

    args = parser.parse_args()

    # Generate
    data = generate_placeholders(
        template_key=args.template_key,
        business_name=args.business_name,
        category=args.category,
        city=args.city,
        phone=args.phone,
        email=args.email,
        address=args.address,
        description=args.description,
        values=args.values,
        opening_hours=args.opening_hours,
        model=args.model,
    )

    # Save
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
