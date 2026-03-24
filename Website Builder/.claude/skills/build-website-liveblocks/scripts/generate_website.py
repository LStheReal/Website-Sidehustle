#!/usr/bin/env python3
"""
Liveblocks-Inspired Template — Website Generator

Takes business data (JSON file or dict) and generates a complete static website
using the liveblocks-inspired template. Modern dark/light SaaS-style design
with gradient accents, service cards, feature highlight, and multi-column footer.

Best for: Tech companies, startups, digital agencies, IT services, SaaS businesses,
modern professional services.

Usage:
    python3 generate_website.py --input business_data.json --output ./output/my-business

Data Schema (JSON):
{
    "BUSINESS_NAME": "TechVision GmbH",
    "TAGLINE": "Digitale Lösungen für Ihr Unternehmen",
    "PHONE": "+41 44 555 66 77",
    "EMAIL": "info@techvision.ch",
    "ADDRESS": "Technoparkstrasse 1, 8005 Zürich",
    ...
}
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from execution.website_utils import copy_template, fill_directory, validate_output
from execution.business_images import suggest_business_images
from execution.copy_enrichment import enrich_template_copy
from execution.website_storage import get_design_output_dir

# Path to the template directory (relative to this script)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"
TEMPLATE_KEY = "liveblocks"

# All supported placeholders with their default fallback values (German)
PLACEHOLDER_DEFAULTS = {
    # --- Core Business Info ---
    "BUSINESS_NAME": "Unser Unternehmen",
    "BUSINESS_NAME_SHORT": "Unternehmen",
    "TAGLINE": "Professionelle Lösungen für Ihr Unternehmen",
    "META_DESCRIPTION": "",

    # --- Hero Section ---
    "SECTION_LABEL_HERO": "Willkommen",
    "HERO_TITLE_LINE1": "Innovative",
    "HERO_TITLE_LINE2": "Lösungen für",
    "HERO_WORD_1": "Ihren Erfolg.",
    "HERO_WORD_2": "Ihre Zukunft.",
    "HERO_WORD_3": "Ihr Wachstum.",
    "HERO_WORD_4": "Ihr Unternehmen.",
    "HERO_DESCRIPTION": "Wir unterstützen Unternehmen mit massgeschneiderten Lösungen — von der Strategie bis zur Umsetzung. Zuverlässig, effizient und zukunftsorientiert.",
    "CTA_BUTTON_PRIMARY": "Kontakt aufnehmen",
    "CTA_BUTTON_SECONDARY": "Leistungen entdecken",

    # --- Trust Bar / Stats ---
    "TRUST_LABEL": "In Zahlen",
    "STAT_1_NUMBER": "10+",
    "STAT_1_LABEL": "Jahre Erfahrung",
    "STAT_2_NUMBER": "500+",
    "STAT_2_LABEL": "Zufriedene Kunden",
    "STAT_3_NUMBER": "50+",
    "STAT_3_LABEL": "Projekte pro Jahr",
    "STAT_4_NUMBER": "100%",
    "STAT_4_LABEL": "Engagement",

    # --- Services Section ---
    "SECTION_LABEL_SERVICES": "Unsere Leistungen",
    "SERVICES_HEADING": "Was wir für Sie tun können",
    "SERVICES_DESCRIPTION": "Von der Beratung bis zur Umsetzung — wir bieten ein umfassendes Leistungsportfolio für Ihre Anforderungen.",
    "SERVICE_1_TITLE": "Beratung",
    "SERVICE_1_DESCRIPTION": "Strategische Beratung für Ihre individuellen Anforderungen und Ziele.",
    "SERVICE_2_TITLE": "Entwicklung",
    "SERVICE_2_DESCRIPTION": "Professionelle Umsetzung mit modernsten Technologien und Methoden.",
    "SERVICE_3_TITLE": "Sicherheit",
    "SERVICE_3_DESCRIPTION": "Höchste Sicherheitsstandards zum Schutz Ihrer Daten und Systeme.",
    "SERVICE_4_TITLE": "Support",
    "SERVICE_4_DESCRIPTION": "Schnelle und zuverlässige Unterstützung — rund um die Uhr für Sie da.",
    "SERVICE_5_TITLE": "Schulung",
    "SERVICE_5_DESCRIPTION": "Massgeschneiderte Schulungen für Ihr Team, damit alle profitieren.",
    "SERVICE_6_TITLE": "Qualität",
    "SERVICE_6_DESCRIPTION": "Strenge Qualitätskontrolle und kontinuierliche Verbesserung unserer Arbeit.",

    # --- Feature Highlight ---
    "SECTION_LABEL_FEATURE": "Warum wir",
    "FEATURE_HEADING": "Erstklassige Ergebnisse durch bewährte Methoden",
    "FEATURE_DESCRIPTION": "Unser Team kombiniert langjährige Erfahrung mit innovativen Ansätzen, um für Sie die bestmöglichen Ergebnisse zu erzielen.",
    "FEATURE_POINT_1": "Individuelle Lösungen, massgeschneidert auf Ihre Bedürfnisse",
    "FEATURE_POINT_2": "Transparente Kommunikation und regelmässige Updates",
    "FEATURE_POINT_3": "Langfristige Partnerschaft statt einmaliger Zusammenarbeit",

    # --- About Section ---
    "SECTION_LABEL_ABOUT": "Über uns",
    "ABOUT_HEADING": "Erfahrung trifft Innovation",
    "ABOUT_LEAD": "Wir sind ein engagiertes Team von Experten, das sich der Qualität und Kundenzufriedenheit verschrieben hat.",
    "ABOUT_DESCRIPTION": "Seit unserer Gründung arbeiten wir eng mit unseren Kunden zusammen, um massgeschneiderte Lösungen zu entwickeln. Unser Ansatz verbindet bewährte Methoden mit innovativem Denken.",
    "VALUE_1_TITLE": "Qualität",
    "VALUE_1_DESCRIPTION": "Wir setzen auf höchste Qualitätsstandards bei jedem Projekt und jeder Dienstleistung.",
    "VALUE_2_TITLE": "Innovation",
    "VALUE_2_DESCRIPTION": "Neue Wege gehen und kreative Lösungen finden — das treibt uns täglich an.",
    "VALUE_3_TITLE": "Vertrauen",
    "VALUE_3_DESCRIPTION": "Langfristige Kundenbeziehungen basieren auf gegenseitigem Vertrauen und Transparenz.",

    # --- CTA Section ---
    "CTA_HEADING_LINE1": "Bereit für den",
    "CTA_HEADING_LINE2": "nächsten Schritt?",
    "CTA_DESCRIPTION": "Lassen Sie uns gemeinsam Ihre Ziele erreichen. Kontaktieren Sie uns für ein unverbindliches Erstgespräch.",

    # --- Contact Section ---
    "CONTACT_CARD_1_TITLE": "Anrufen",
    "CONTACT_CARD_1_DESCRIPTION": "Sprechen Sie direkt mit unserem Team für eine persönliche Beratung.",
    "CONTACT_CARD_2_TITLE": "Schreiben",
    "CONTACT_CARD_2_DESCRIPTION": "Senden Sie uns eine Nachricht und wir melden uns schnellstmöglich zurück.",
    "PHONE": "",
    "PHONE_SHORT": "",
    "EMAIL": "",
    "ADDRESS": "",
    "OPENING_HOURS": "Mo–Fr 08:00–18:00",

    # --- Footer ---
    "FOOTER_COL_1_TITLE": "Leistungen",
    "FOOTER_COL_1_LINK_1": "Beratung",
    "FOOTER_COL_1_LINK_2": "Entwicklung",
    "FOOTER_COL_1_LINK_3": "Support",
    "FOOTER_COL_2_TITLE": "Unternehmen",
    "FOOTER_COL_2_LINK_1": "Über uns",
    "FOOTER_COL_2_LINK_2": "Kontakt",
    "FOOTER_COL_2_LINK_3": "Impressum",
    "IMAGE_FEATURE": "assets/images/feature.svg",
    "IMAGE_ABOUT": "assets/images/about.svg",
}

IMAGE_SLOT_MAP = {
    "IMAGE_FEATURE": "feature",
    "IMAGE_ABOUT": "about",
}


def load_business_data(input_path: str) -> dict:
    """Load business data from a JSON file."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def merge_with_defaults(data: dict) -> dict:
    """
    Merge provided business data with default fallback values.
    Provided values override defaults. Empty strings are kept.
    """
    merged = dict(PLACEHOLDER_DEFAULTS)
    for key, value in data.items():
        if value is not None:
            merged[key] = value

    # Auto-generate BUSINESS_NAME_SHORT if not provided
    if "BUSINESS_NAME_SHORT" not in data and "BUSINESS_NAME" in data:
        name = data["BUSINESS_NAME"]
        parts = name.split()
        if len(parts) >= 2:
            merged["BUSINESS_NAME_SHORT"] = parts[0]
        else:
            merged["BUSINESS_NAME_SHORT"] = name

    # Auto-generate PHONE_SHORT from PHONE if not provided
    if "PHONE_SHORT" not in data and merged.get("PHONE"):
        merged["PHONE_SHORT"] = merged["PHONE"]

    # Auto-generate META_DESCRIPTION if not provided
    if not merged.get("META_DESCRIPTION"):
        name = merged.get("BUSINESS_NAME", "")
        tagline = merged.get("TAGLINE", "")
        if name and tagline:
            merged["META_DESCRIPTION"] = f"{name} — {tagline}"
        elif name:
            merged["META_DESCRIPTION"] = name

    # Auto-populate footer links from services if not explicitly set
    if "FOOTER_COL_1_LINK_1" not in data and "SERVICE_1_TITLE" in data:
        merged["FOOTER_COL_1_LINK_1"] = data.get("SERVICE_1_TITLE", merged["FOOTER_COL_1_LINK_1"])
    if "FOOTER_COL_1_LINK_2" not in data and "SERVICE_2_TITLE" in data:
        merged["FOOTER_COL_1_LINK_2"] = data.get("SERVICE_2_TITLE", merged["FOOTER_COL_1_LINK_2"])
    if "FOOTER_COL_1_LINK_3" not in data and "SERVICE_3_TITLE" in data:
        merged["FOOTER_COL_1_LINK_3"] = data.get("SERVICE_3_TITLE", merged["FOOTER_COL_1_LINK_3"])
    merged = enrich_template_copy(merged, "liveblocks")

    merged.setdefault("TEMPLATE_NAME", "liveblocks")
    auto_images = suggest_business_images(merged, IMAGE_SLOT_MAP)
    for placeholder, image_url in auto_images.items():
        if not data.get(placeholder):
            merged[placeholder] = image_url

    return merged


def generate_website(data: dict, output_dir: str, overwrite: bool = False) -> dict:
    """
    Generate a complete static website from business data.

    Args:
        data: Business data dictionary with placeholder values.
        output_dir: Where to output the generated website.
        overwrite: Whether to replace existing output directory.

    Returns:
        Dict with generation results.
    """
    # Step 1: Merge with defaults
    merged_data = merge_with_defaults(data)
    print(f"Generating website for: {merged_data.get('BUSINESS_NAME', 'Unknown')}")

    # Step 2: Copy template to output
    output_path = copy_template(str(TEMPLATE_DIR), output_dir, overwrite=overwrite)

    # Step 3: Fill all placeholders
    replacements = fill_directory(output_path, merged_data)
    total_replacements = sum(replacements.values())
    print(f"Replaced {total_replacements} placeholders across {len(replacements)} files")

    # Step 4: Validate output
    validation = validate_output(output_path)
    if validation["valid"]:
        print("Validation passed — all placeholders filled")
    else:
        print(f"WARNING: {len(validation['unfilled'])} unfilled placeholders remain:")
        for file_path, placeholder in validation["unfilled"]:
            print(f"  - {file_path}: {{{{{placeholder}}}}}")

    return {
        "output_dir": output_path,
        "replacements": replacements,
        "validation": validation,
        "data_used": merged_data,
    }


def cli_to_data(args) -> dict:
    """Convert CLI arguments to a data dictionary."""
    data = {}
    if args.business_name:
        data["BUSINESS_NAME"] = args.business_name
    if args.tagline:
        data["TAGLINE"] = args.tagline
    if args.phone:
        data["PHONE"] = args.phone
    if args.email:
        data["EMAIL"] = args.email
    if args.address:
        data["ADDRESS"] = args.address
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate a website from the Liveblocks-inspired template using business data."
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to a JSON file containing business data."
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory for the generated website."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output directory."
    )

    # Inline data arguments
    parser.add_argument("--business-name", help="Business name")
    parser.add_argument("--tagline", help="Business tagline")
    parser.add_argument("--phone", help="Phone number")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--address", help="Business address")

    args = parser.parse_args()

    # Load data from JSON file or CLI arguments
    if args.input:
        data = load_business_data(args.input)
        print(f"Loaded data from {args.input}")
    else:
        data = cli_to_data(args)
        if not data:
            print("Error: Provide either --input JSON file or inline arguments.")
            sys.exit(1)

    # Generate the website
    output_dir = args.output
    if not output_dir:
        output_dir = str(get_design_output_dir(PROJECT_ROOT, data.get("BUSINESS_NAME", ""), TEMPLATE_KEY))
        print(f"No --output provided. Using default: {output_dir}")

    result = generate_website(data, output_dir, overwrite=args.overwrite)

    # Summary
    print(f"\nWebsite generated at: {result['output_dir']}")
    if result["validation"]["valid"]:
        print("Status: READY TO DEPLOY")
    else:
        print("Status: NEEDS REVIEW (unfilled placeholders)")

    return result


if __name__ == "__main__":
    main()
