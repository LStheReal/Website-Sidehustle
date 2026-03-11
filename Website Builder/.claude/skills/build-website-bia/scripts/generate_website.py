#!/usr/bin/env python3
"""
BiA (Build in Amsterdam) Template — Website Generator

Takes business data (JSON file or dict) and generates a complete static website
using the buildinamsterdam-inspired template. Editorial design with serif headings,
split-screen sections, and gold accent details.

Best for: Agencies, consultancies, professional service firms, creative studios.

Usage:
    python3 generate_website.py --input business_data.json --output ./output/my-business

Data Schema (JSON):
{
    "BUSINESS_NAME": "Architekturbüro Weber",
    "BUSINESS_NAME_SHORT": "Weber.",
    "TAGLINE": "Architektur & Design in Zürich",
    "META_DESCRIPTION": "Architekturbüro Weber — Moderne Architektur...",
    "SECTION_LABEL_HERO": "Architektur & Design",
    "HERO_TITLE_LINE1": "Wir gestalten",
    "HERO_TITLE_LINE2": "Räume, die",
    "HERO_TITLE_LINE3": "inspirieren.",
    "INTRO_TEXT": "Seit 15 Jahren entwerfen wir Gebäude...",
    "INTRO_DESCRIPTION": "Von der ersten Skizze bis zur Schlüsselübergabe...",
    "SECTION_LABEL_SERVICES": "Unsere Leistungen",
    "SERVICES_HEADING": "Architektur von der Planung bis zur Umsetzung",
    "SERVICE_1_TITLE": "Entwurfsplanung",
    "SERVICE_1_DESCRIPTION": "Kreative Konzepte...",
    "SERVICE_2_TITLE": "Bauplanung",
    "SERVICE_2_DESCRIPTION": "Detaillierte Pläne...",
    "SERVICE_3_TITLE": "Bauleitung",
    "SERVICE_3_DESCRIPTION": "Professionelle Begleitung...",
    "SERVICE_4_TITLE": "Innenarchitektur",
    "SERVICE_4_DESCRIPTION": "Individuelle Raumgestaltung...",
    "SECTION_LABEL_ABOUT": "Über uns",
    "ABOUT_HEADING": "Moderne Architektur mit Tradition",
    "ABOUT_DESCRIPTION": "Unser Büro vereint...",
    "STAT_1_NUMBER": "15+",
    "STAT_1_LABEL": "Jahre Erfahrung",
    "STAT_2_NUMBER": "200+",
    "STAT_2_LABEL": "Projekte realisiert",
    "STAT_3_NUMBER": "12",
    "STAT_3_LABEL": "Teammitglieder",
    "CTA_TITLE_LINE1": "Projekt",
    "CTA_TITLE_LINE2": "geplant?",
    "CTA_TITLE_LINE3": "Sprechen wir darüber.",
    "PHONE": "+41 44 123 45 67",
    "EMAIL": "info@weber-architektur.ch",
    "ADDRESS": "Limmatstrasse 50, 8005 Zürich",
    "OPENING_HOURS": "Mo–Fr 08:00–18:00"
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

# Path to the template directory (relative to this script)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"

# All supported placeholders with their default fallback values
PLACEHOLDER_DEFAULTS = {
    "BUSINESS_NAME": "Unser Unternehmen",
    "BUSINESS_NAME_SHORT": "Unternehmen.",
    "TAGLINE": "Professionelle Dienstleistungen",
    "META_DESCRIPTION": "",
    "SECTION_LABEL_HERO": "Willkommen",
    "HERO_TITLE_LINE1": "Wir bieten",
    "HERO_TITLE_LINE2": "erstklassige",
    "HERO_TITLE_LINE3": "Dienstleistungen.",
    "INTRO_TEXT": "Wir sind Ihr zuverlässiger Partner für professionelle Dienstleistungen in der Region.",
    "INTRO_DESCRIPTION": "Mit jahrelanger Erfahrung und einem engagierten Team stehen wir Ihnen zur Seite. Qualität und Kundenzufriedenheit stehen bei uns an erster Stelle.",
    "SECTION_LABEL_SERVICES": "Unsere Leistungen",
    "SERVICES_HEADING": "Was wir für Sie tun können",
    "SERVICE_1_TITLE": "Beratung",
    "SERVICE_1_DESCRIPTION": "Individuelle Beratung zugeschnitten auf Ihre Bedürfnisse.",
    "SERVICE_2_TITLE": "Planung",
    "SERVICE_2_DESCRIPTION": "Sorgfältige Planung für optimale Ergebnisse.",
    "SERVICE_3_TITLE": "Umsetzung",
    "SERVICE_3_DESCRIPTION": "Professionelle Umsetzung mit Liebe zum Detail.",
    "SERVICE_4_TITLE": "Betreuung",
    "SERVICE_4_DESCRIPTION": "Langfristige Betreuung und Unterstützung nach Abschluss.",
    "SECTION_LABEL_ABOUT": "Über uns",
    "ABOUT_HEADING": "Erfahrung trifft Leidenschaft",
    "ABOUT_DESCRIPTION": "Unser Team vereint langjährige Erfahrung mit frischen Ideen. Wir arbeiten eng mit unseren Kunden zusammen, um die bestmöglichen Ergebnisse zu erzielen.",
    "STAT_1_NUMBER": "10+",
    "STAT_1_LABEL": "Jahre Erfahrung",
    "STAT_2_NUMBER": "500+",
    "STAT_2_LABEL": "Zufriedene Kunden",
    "STAT_3_NUMBER": "100%",
    "STAT_3_LABEL": "Einsatz",
    "CTA_TITLE_LINE1": "Projekt",
    "CTA_TITLE_LINE2": "geplant?",
    "CTA_TITLE_LINE3": "Sprechen wir darüber.",
    "PHONE": "",
    "EMAIL": "",
    "ADDRESS": "",
    "OPENING_HOURS": "Mo–Fr 08:00–18:00",
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
        # Take first word + period, or abbreviate
        parts = name.split()
        if len(parts) >= 2:
            merged["BUSINESS_NAME_SHORT"] = parts[0] + "."
        else:
            merged["BUSINESS_NAME_SHORT"] = name + "."

    # Auto-generate META_DESCRIPTION if not provided
    if not merged.get("META_DESCRIPTION"):
        name = merged.get("BUSINESS_NAME", "")
        tagline = merged.get("TAGLINE", "")
        if name and tagline:
            merged["META_DESCRIPTION"] = f"{name} — {tagline}"
        elif name:
            merged["META_DESCRIPTION"] = name

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
        description="Generate a website from the BiA template using business data."
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to a JSON file containing business data."
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
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
    result = generate_website(data, args.output, overwrite=args.overwrite)

    # Summary
    print(f"\nWebsite generated at: {result['output_dir']}")
    if result["validation"]["valid"]:
        print("Status: READY TO DEPLOY")
    else:
        print("Status: NEEDS REVIEW (unfilled placeholders)")

    return result


if __name__ == "__main__":
    main()
