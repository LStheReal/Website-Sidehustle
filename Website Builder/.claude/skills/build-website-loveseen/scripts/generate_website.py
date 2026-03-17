#!/usr/bin/env python3
"""
LoveSeen-Inspired Template — Website Generator

Takes business data (JSON file or dict) and generates a complete static website
using the loveseen-inspired editorial beauty template. Warm cream palette, high-contrast
serif typography, full-bleed hero, polaroid-style about image, statement section, gallery.

Best for: Beauty salons, spas, photographers, makeup artists, wellness studios,
life coaches, personal brands — any service business with a luxury/editorial feel.

Usage:
    python3 generate_website.py --input business_data.json --output ./output/my-business

Data Schema (JSON):
{
    "BUSINESS_NAME": "Studio Mara",
    "TAGLINE": "Haar & Schönheit in Zürich",
    "PHONE": "+41 44 123 45 67",
    "EMAIL": "hallo@studiomara.ch",
    "ADDRESS": "Langstrasse 12, 8004 Zürich",
    "OPENING_HOURS": "Di–Sa 9–18 Uhr",
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

# Path to the template directory (relative to this script)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"

# All supported placeholders with German fallback defaults
PLACEHOLDER_DEFAULTS = {
    # --- Core ---
    "BUSINESS_NAME":            "Studio Mara",
    "TAGLINE":                  "Schönheit & Wohlbefinden",
    "META_DESCRIPTION":         "",

    # --- Nav ---
    "NAV_CTA":                  "Termin buchen",
    "NAV_LINK_1":               "Über uns",
    "NAV_LINK_2":               "Leistungen",
    "NAV_LINK_3":               "Galerie",
    "NAV_LINK_4":               "Kontakt",

    # --- Hero ---
    "HERO_TITLE_LINE1":         "Deine Schönheit,",
    "HERO_TITLE_LINE2":         "unser Handwerk",
    "HERO_CTA":                 "Entdecken",

    # --- About ---
    "SECTION_LABEL_ABOUT":      "Über uns",
    "ABOUT_HEADING_LINE1":      "Eine wahre Geschichte",
    "ABOUT_HEADING_LINE2":      "über echte Schönheit",
    "ABOUT_LEAD":               "Wir glauben, dass Schönheit von innen kommt — und ein bisschen Handwerk von uns.",
    "ABOUT_DESCRIPTION":        "Unser Studio wurde mit einer einfachen Überzeugung gegründet: Jeder Mensch verdient ein Erlebnis, das sich besonders anfühlt. Wir verbinden Können mit Herzlichkeit.",
    "ABOUT_CTA":                "Unsere Leistungen",

    # --- Statement ---
    "STATEMENT_LABEL":          "Unser Versprechen",
    "STATEMENT_LINE1":          "Es geht nicht",
    "STATEMENT_LINE2":          "um Perfektion —",
    "STATEMENT_LINE3":          "sondern um dich.",

    # --- Services ---
    "SECTION_LABEL_SERVICES":   "Was wir tun",
    "SERVICES_HEADING":         "Unsere Leistungen",
    "SERVICE_1_TITLE":          "Haarpflege",
    "SERVICE_1_DESCRIPTION":    "Schnitte, Farbe und Treatments, die zu dir passen — nicht zum Trend.",
    "SERVICE_2_TITLE":          "Make-up",
    "SERVICE_2_DESCRIPTION":    "Alltags-Make-up bis Braut-Look. Natürlich, präzise, du.",
    "SERVICE_3_TITLE":          "Wellness",
    "SERVICE_3_DESCRIPTION":    "Gesichtsbehandlungen und Pflegepakete für dein Wohlbefinden.",
    "SERVICES_CTA":             "Termin vereinbaren",

    # --- Gallery ---
    "GALLERY_LABEL":            "Folg uns",
    "INSTAGRAM_HANDLE":         "studiomara",
    "INSTAGRAM_URL":            "#",

    # --- Contact ---
    "CONTACT_TAGLINE":          "Zeig uns dein Lächeln, wir zeigen dir unseres.",
    "EMAIL_PLACEHOLDER":        "Deine E-Mail-Adresse",
    "CONTACT_LABEL_PHONE":      "Telefon",
    "CONTACT_LABEL_EMAIL":      "E-Mail",
    "CONTACT_LABEL_ADDRESS":    "Adresse",
    "CONTACT_LABEL_HOURS":      "Öffnungszeiten",

    # --- Contact Info ---
    "PHONE":                    "+41 44 123 45 67",
    "EMAIL":                    "hallo@studiomara.ch",
    "ADDRESS":                  "Langstrasse 12, 8004 Zürich",
    "OPENING_HOURS":            "Di–Sa 9–18 Uhr",

    # --- Footer ---
    "FOOTER_PRIVACY":           "Datenschutz",
    "FOOTER_TERMS":             "AGB",
    "FOOTER_YEAR":              "2025",
}


def merge_with_defaults(data: dict) -> dict:
    """Merge user data with defaults. Empty strings keep the default."""
    merged = dict(PLACEHOLDER_DEFAULTS)
    for key, value in data.items():
        if value is not None and value != "":
            merged[key] = str(value)

    # Auto-generate META_DESCRIPTION if not provided
    if not merged.get("META_DESCRIPTION"):
        name = merged.get("BUSINESS_NAME", "")
        tagline = merged.get("TAGLINE", "")
        merged["META_DESCRIPTION"] = f"{name} — {tagline}" if tagline else name

    return merged


def generate_website(data: dict, output_dir: str, overwrite: bool = False) -> dict:
    """
    Generate a complete static website from business data.

    Args:
        data: Business data dictionary with placeholder values
        output_dir: Path where the generated site should be written
        overwrite: If True, overwrite existing output directory

    Returns:
        dict with output_dir and validation results
    """
    merged = merge_with_defaults(data)
    output_path = copy_template(str(TEMPLATE_DIR), output_dir, overwrite=overwrite)
    replacements = fill_directory(output_path, merged)
    validation = validate_output(output_path)
    return {
        "output_dir": output_path,
        "replacements": replacements,
        "validation": validation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate a loveseen-style website from business data"
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to JSON file with business data"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output directory for generated website"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output directory if it exists"
    )
    # Inline overrides
    parser.add_argument("--business-name", help="Business name")
    parser.add_argument("--tagline", help="Tagline")
    parser.add_argument("--phone", help="Phone number")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--address", help="Street address")
    parser.add_argument("--opening-hours", help="Opening hours")
    parser.add_argument("--instagram", help="Instagram handle (without @)")

    args = parser.parse_args()

    # Load base data
    data = {}
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)

    # Apply inline overrides
    overrides = {
        "BUSINESS_NAME": args.business_name,
        "TAGLINE": args.tagline,
        "PHONE": args.phone,
        "EMAIL": args.email,
        "ADDRESS": args.address,
        "OPENING_HOURS": args.opening_hours,
        "INSTAGRAM_HANDLE": args.instagram,
    }
    for key, val in overrides.items():
        if val is not None:
            data[key] = val

    result = generate_website(data, args.output, overwrite=args.overwrite)

    print(f"\n✓ Generated: {result['output_dir']}")
    print(f"  Replaced {result['replacements']} placeholders")

    v = result["validation"]
    if v["unfilled"]:
        print(f"\n⚠ Unfilled placeholders: {v['unfilled']}")
    else:
        print("  Validation passed — READY TO DEPLOY\n")

    return 0 if not v["unfilled"] else 1


if __name__ == "__main__":
    sys.exit(main())
