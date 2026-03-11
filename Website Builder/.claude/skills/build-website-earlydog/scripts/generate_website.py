#!/usr/bin/env python3
"""
EarlyDog Template — Website Generator

Takes business data (JSON file or dict) and generates a complete static website
using the earlydog template. Output is a ready-to-deploy directory.

Usage:
    python3 generate_website.py --input business_data.json --output ./output/my-business

    Or with inline data:
    python3 generate_website.py --output ./output/my-business \
        --business-name "Swiss Textilreinigung" \
        --phone "+41 44 740 13 62" \
        --email "info@example.com" \
        --address "Steinmürlistrasse 38, 8953 Dietikon"

Data Schema (JSON):
{
    "BUSINESS_NAME": "Swiss Textilreinigung",
    "TAGLINE": "Professionelle Textilreinigung in Dietikon",
    "META_DESCRIPTION": "Swiss Textilreinigung bietet professionelle Textilreinigung...",
    "HERO_TITLE_LINE1": "Professionelle",
    "HERO_TITLE_LINE2": "Textilreinigung",
    "HERO_DESCRIPTION": "Seit über 20 Jahren Ihr Partner für saubere Textilien...",
    "SERVICE_1_TITLE": "Textilreinigung",
    "SERVICE_1_DESCRIPTION": "Professionelle Reinigung aller Textilien...",
    "SERVICE_1_CTA": "Mehr erfahren",
    "SERVICE_2_TITLE": "Hemdenservice",
    "SERVICE_2_DESCRIPTION": "Perfekt gebügelte Hemden...",
    "SERVICE_2_CTA": "Mehr erfahren",
    "SERVICE_3_TITLE": "Expressreinigung",
    "SERVICE_3_DESCRIPTION": "Heute abgeben, morgen abholen...",
    "SERVICE_3_CTA": "Mehr erfahren",
    "CTA_TITLE_LINE1": "Interesse geweckt?",
    "CTA_TITLE_LINE2": "Kontaktieren Sie uns.",
    "PHONE": "+41 44 740 13 62",
    "EMAIL": "info@example.com",
    "ADDRESS": "Steinmürlistrasse 38, 8953 Dietikon"
}
"""

import argparse
import json
import os
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
    "TAGLINE": "Ihr Partner vor Ort",
    "META_DESCRIPTION": "",
    "HERO_TITLE_LINE1": "Willkommen bei",
    "HERO_TITLE_LINE2": "unserem Service",
    "HERO_DESCRIPTION": "Wir bieten professionelle Dienstleistungen für Ihr Unternehmen.",
    "SERVICE_1_TITLE": "Service 1",
    "SERVICE_1_DESCRIPTION": "Beschreibung unseres ersten Services.",
    "SERVICE_1_CTA": "Mehr erfahren",
    "SERVICE_2_TITLE": "Service 2",
    "SERVICE_2_DESCRIPTION": "Beschreibung unseres zweiten Services.",
    "SERVICE_2_CTA": "Mehr erfahren",
    "SERVICE_3_TITLE": "Service 3",
    "SERVICE_3_DESCRIPTION": "Beschreibung unseres dritten Services.",
    "SERVICE_3_CTA": "Mehr erfahren",
    "CTA_TITLE_LINE1": "Interesse geweckt?",
    "CTA_TITLE_LINE2": "Kontaktieren Sie uns.",
    "PHONE": "",
    "EMAIL": "",
    "ADDRESS": "",
}


def load_business_data(input_path: str) -> dict:
    """Load business data from a JSON file."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def merge_with_defaults(data: dict) -> dict:
    """
    Merge provided business data with default fallback values.
    Provided values override defaults. Empty strings are kept (not replaced by defaults).
    """
    merged = dict(PLACEHOLDER_DEFAULTS)
    for key, value in data.items():
        if value is not None:
            merged[key] = value

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
        Dict with generation results:
            - "output_dir": path to generated website
            - "replacements": dict of files and replacement counts
            - "validation": validation results
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
    if args.hero_title_1:
        data["HERO_TITLE_LINE1"] = args.hero_title_1
    if args.hero_title_2:
        data["HERO_TITLE_LINE2"] = args.hero_title_2
    if args.hero_description:
        data["HERO_DESCRIPTION"] = args.hero_description
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate a website from the earlydog template using business data."
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

    # Inline data arguments (alternative to --input JSON file)
    parser.add_argument("--business-name", help="Business name")
    parser.add_argument("--tagline", help="Business tagline")
    parser.add_argument("--phone", help="Phone number")
    parser.add_argument("--email", help="Email address")
    parser.add_argument("--address", help="Business address")
    parser.add_argument("--hero-title-1", help="Hero title line 1")
    parser.add_argument("--hero-title-2", help="Hero title line 2")
    parser.add_argument("--hero-description", help="Hero description text")

    args = parser.parse_args()

    # Load data from JSON file or CLI arguments
    if args.input:
        data = load_business_data(args.input)
        print(f"Loaded data from {args.input}")
    else:
        data = cli_to_data(args)
        if not data:
            print("Error: Provide either --input JSON file or inline arguments.")
            print("Run with --help for usage information.")
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
