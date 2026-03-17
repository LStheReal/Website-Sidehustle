#!/usr/bin/env python3
"""
replace_images.py — Intelligent image replacement for adapted websites.

Takes a built website directory, a logo, and uploaded images with a placement
mapping (decided by Claude), and replaces SVG placeholders with real images.

Usage:
    python3 replace_images.py \
        --website-dir .tmp/adapted_website \
        --logo /path/to/logo.png \
        --images /path/to/photo1.jpg /path/to/photo2.jpg \
        --template-key bia \
        --placement '{"hero": "photo1.jpg", "showcase": "photo2.jpg"}'
"""

import argparse
import json
import os
import shutil
import sys

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 required. Install with: pip install beautifulsoup4")
    sys.exit(1)

# Image slot names per template — maps slot name to the SVG filename it replaces
TEMPLATE_SLOTS = {
    "earlydog": {
        "hero": "hero.svg",
        "section1": "section1.svg",
        "section2": "section2.svg",
        "section3": "section3.svg",
    },
    "bia": {
        "hero": "hero.svg",
        "showcase": "showcase.svg",
        "cta": "cta.svg",
        "contact": "contact.svg",
    },
    "liveblocks": {
        "feature": "feature.svg",
        "about": "about.svg",
    },
    "loveseen": {
        "hero": "hero.svg",
        "about": "about.svg",
        "gallery1": "gallery1.svg",
        "gallery2": "gallery2.svg",
        "gallery3": "gallery3.svg",
    },
}


def replace_logo(html_path: str, logo_path: str) -> None:
    """Replace nav-logo and footer-logo with the uploaded logo image."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Determine the relative path from the HTML file to the logo
    logo_filename = os.path.basename(logo_path)
    logo_src = f"assets/images/{logo_filename}"

    # Replace nav logo
    nav_logo = soup.select_one(".nav-logo")
    if nav_logo:
        # If it's a link, keep the link but replace inner content
        if nav_logo.name == "a":
            nav_logo.clear()
            img = soup.new_tag("img", src=logo_src, alt="Logo")
            img["style"] = "height: 40px; width: auto; object-fit: contain;"
            nav_logo.append(img)
        else:
            # It's a div or similar — find the link inside or replace content
            link = nav_logo.find("a")
            if link:
                link.clear()
                img = soup.new_tag("img", src=logo_src, alt="Logo")
                img["style"] = "height: 40px; width: auto; object-fit: contain;"
                link.append(img)
            else:
                nav_logo.clear()
                img = soup.new_tag("img", src=logo_src, alt="Logo")
                img["style"] = "height: 40px; width: auto; object-fit: contain;"
                nav_logo.append(img)

    # Replace footer logo
    for selector in [".footer-logo", ".footer-logo-text", "span.footer-logo"]:
        footer_logo = soup.select_one(selector)
        if footer_logo:
            footer_logo.clear()
            img = soup.new_tag("img", src=logo_src, alt="Logo")
            img["style"] = "height: 32px; width: auto; object-fit: contain;"
            footer_logo.append(img)
            break

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print(f"  ✓ Logo injected into nav and footer: {logo_filename}")


def replace_images(
    website_dir: str,
    template_key: str,
    images: list[str],
    placement: dict[str, str],
) -> None:
    """Replace SVG placeholder images with uploaded images based on placement mapping."""
    slots = TEMPLATE_SLOTS.get(template_key)
    if not slots:
        print(f"  ⚠ Unknown template key: {template_key}")
        return

    images_dir = os.path.join(website_dir, "assets", "images")
    html_path = os.path.join(website_dir, "index.html")

    # Build a lookup: image basename → full path
    image_lookup = {}
    for img_path in images:
        image_lookup[os.path.basename(img_path)] = img_path

    # Process each placement decision
    replacements_made = []
    for slot_name, image_basename in placement.items():
        if slot_name not in slots:
            print(f"  ⚠ Unknown slot '{slot_name}' for template '{template_key}', skipping")
            continue

        src_path = image_lookup.get(image_basename)
        if not src_path or not os.path.exists(src_path):
            print(f"  ⚠ Image not found: {image_basename}, skipping slot '{slot_name}'")
            continue

        svg_filename = slots[slot_name]
        # Determine the new filename (keep original extension)
        ext = os.path.splitext(image_basename)[1] or ".jpg"
        new_filename = os.path.splitext(svg_filename)[0] + ext

        # Copy the image to assets/images/, replacing the SVG
        dest_path = os.path.join(images_dir, new_filename)
        shutil.copy2(src_path, dest_path)

        # Remove the old SVG if it still exists and we're using a different extension
        old_svg_path = os.path.join(images_dir, svg_filename)
        if os.path.exists(old_svg_path) and new_filename != svg_filename:
            os.remove(old_svg_path)

        replacements_made.append((slot_name, svg_filename, new_filename))

    # Update HTML src attributes
    if replacements_made:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        for slot_name, old_file, new_file in replacements_made:
            # Replace both quoted styles
            html = html.replace(f'src="assets/images/{old_file}"', f'src="assets/images/{new_file}"')
            html = html.replace(f"src='assets/images/{old_file}'", f"src='assets/images/{new_file}'")
            print(f"  ✓ {slot_name}: {old_file} → {new_file}")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

    if not replacements_made:
        print("  ℹ No image replacements made (no valid placements)")


def main():
    parser = argparse.ArgumentParser(description="Replace template images with uploaded customer images")
    parser.add_argument("--website-dir", required=True, help="Path to the built website directory")
    parser.add_argument("--logo", default="", help="Path to the customer's logo file")
    parser.add_argument("--images", nargs="*", default=[], help="Paths to customer image files")
    parser.add_argument("--template-key", required=True, choices=list(TEMPLATE_SLOTS.keys()),
                        help="Template identifier")
    parser.add_argument("--placement", default="{}", help="JSON mapping: slot name → image filename")
    args = parser.parse_args()

    if not os.path.isdir(args.website_dir):
        print(f"ERROR: Website directory not found: {args.website_dir}")
        sys.exit(1)

    html_path = os.path.join(args.website_dir, "index.html")
    if not os.path.exists(html_path):
        print(f"ERROR: index.html not found in {args.website_dir}")
        sys.exit(1)

    print(f"Replacing images in: {args.website_dir}")
    print(f"Template: {args.template_key}")

    # Handle logo
    if args.logo and os.path.exists(args.logo):
        # Copy logo to assets/images/
        images_dir = os.path.join(args.website_dir, "assets", "images")
        os.makedirs(images_dir, exist_ok=True)
        logo_dest = os.path.join(images_dir, os.path.basename(args.logo))
        shutil.copy2(args.logo, logo_dest)
        replace_logo(html_path, args.logo)
    elif args.logo:
        print(f"  ⚠ Logo file not found: {args.logo}")

    # Handle images with placement
    if args.images:
        try:
            placement = json.loads(args.placement)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid placement JSON: {args.placement}")
            sys.exit(1)

        replace_images(args.website_dir, args.template_key, args.images, placement)

    print("Done!")


if __name__ == "__main__":
    main()
