# Build Website — LoveSeen Template

## When to Use

Use this skill when a client runs a **beauty, wellness, or personal brand service business** and wants a website with a **luxury editorial aesthetic**. This template captures the warm, intimate, high-fashion feel of loveseen.com — without any shop or e-commerce sections.

**Best for:**
- Hair salons & beauty studios
- Makeup artists & beauticians
- Photographers & videographers
- Wellness studios & spas
- Life coaches & personal brands
- Yoga / pilates studios
- Any service business that wants an editorial, intimate, luxury feel

**Not ideal for:** Trades, tech companies, medical/legal firms, corporate businesses.

---

## Design System

| Property | Value |
|----------|-------|
| Background | `#FAF6F5` — warm cream |
| Accent | `#F2E8E5` — blush pink (statement + contact + footer sections) |
| Text | `#00091B` — near black |
| Muted | `#9A8F8A` — warm grey (labels, captions) |
| Heading font | Cormorant Garamond (Google Fonts) — high-contrast editorial serif |
| Body font | DM Sans (Google Fonts) — clean, modern sans |
| Style | Full-bleed hero, polaroid-frame about image, statement typography, gallery grid |

---

## Sections

1. **Nav** — centered logo (all-caps serif), hamburger left → fullscreen overlay menu, CTA link right
2. **Hero** — full-bleed dark image, large serif title (line 1 uppercase + line 2 italic), ghost outline button
3. **About** — small label, 2-col layout (text + polaroid-framed image), outline CTA button
4. **Statement** — blush bg, large editorial 3-line serif quote/promise
5. **Services** — 3-column numbered grid (01/02/03) with titles and descriptions, outline CTA
6. **Gallery** — 3-photo full-bleed grid (2fr + 1fr + 1fr) + @instagram handle
7. **Contact** — blush bg, centered logo, newsletter signup, 2×2 contact details grid
8. **Footer** — dark navy, Instagram icon, privacy/terms, copyright

---

## Data Schema

```json
{
    "BUSINESS_NAME":            "Atelier Léa",
    "TAGLINE":                  "Haar & Schönheit in Zürich",
    "META_DESCRIPTION":         "Auto-generated if empty",

    "NAV_CTA":                  "Termin buchen",
    "NAV_LINK_1":               "Über uns",
    "NAV_LINK_2":               "Leistungen",
    "NAV_LINK_3":               "Galerie",
    "NAV_LINK_4":               "Kontakt",

    "HERO_TITLE_LINE1":         "Dein Haar,",
    "HERO_TITLE_LINE2":         "deine Geschichte",
    "HERO_CTA":                 "OH HI",

    "SECTION_LABEL_ABOUT":      "Unsere Geschichte",
    "ABOUT_HEADING_LINE1":      "Eine wahre Geschichte",
    "ABOUT_HEADING_LINE2":      "über echtes Handwerk",
    "ABOUT_LEAD":               "Short punchy lead sentence (1–2 lines).",
    "ABOUT_DESCRIPTION":        "Longer body copy (2–4 sentences).",
    "ABOUT_CTA":                "Unsere Leistungen",

    "STATEMENT_LABEL":          "Unser Versprechen",
    "STATEMENT_LINE1":          "Nicht der Trend —",
    "STATEMENT_LINE2":          "sondern du",
    "STATEMENT_LINE3":          "stehst im Mittelpunkt.",

    "SECTION_LABEL_SERVICES":   "Was wir anbieten",
    "SERVICES_HEADING":         "Unsere Leistungen",
    "SERVICE_1_TITLE":          "Haarpflege",
    "SERVICE_1_DESCRIPTION":    "Short description (1–2 sentences).",
    "SERVICE_2_TITLE":          "Make-up",
    "SERVICE_2_DESCRIPTION":    "Short description.",
    "SERVICE_3_TITLE":          "Behandlungen",
    "SERVICE_3_DESCRIPTION":    "Short description.",
    "SERVICES_CTA":             "Termin vereinbaren",

    "GALLERY_LABEL":            "Folg uns",
    "INSTAGRAM_HANDLE":         "atelierlea_zh",
    "INSTAGRAM_URL":            "https://instagram.com/atelierlea_zh",

    "CONTACT_TAGLINE":          "Zeig uns dein Lächeln, wir zeigen dir unseres.",
    "EMAIL_PLACEHOLDER":        "Deine E-Mail-Adresse",
    "CONTACT_LABEL_PHONE":      "Telefon",
    "CONTACT_LABEL_EMAIL":      "E-Mail",
    "CONTACT_LABEL_ADDRESS":    "Adresse",
    "CONTACT_LABEL_HOURS":      "Öffnungszeiten",

    "PHONE":                    "+41 44 210 33 55",
    "EMAIL":                    "hallo@atelierlea.ch",
    "ADDRESS":                  "Augustinergasse 7, 8001 Zürich",
    "OPENING_HOURS":            "Di–Fr 9–19 Uhr, Sa 9–17 Uhr",

    "FOOTER_PRIVACY":           "Datenschutz",
    "FOOTER_TERMS":             "AGB",
    "FOOTER_YEAR":              "2025"
}
```

---

## How to Run

```bash
cd "Website Builder"
source .venv/bin/activate

# From JSON file
python3 .claude/skills/build-website-loveseen/scripts/generate_website.py \
    --input .tmp/my_client.json \
    --output .tmp/my_client_website \
    --overwrite

# Inline flags
python3 .claude/skills/build-website-loveseen/scripts/generate_website.py \
    --business-name "Studio Luna" \
    --tagline "Yoga & Wellness in Bern" \
    --phone "+41 31 555 66 77" \
    --email "hi@studioluna.ch" \
    --address "Marktgasse 4, 3011 Bern" \
    --opening-hours "Mo–Sa 8–20 Uhr" \
    --instagram studioluna_bern \
    --output .tmp/studioluna_website \
    --overwrite
```

**Expected output:**
```
✓ Generated: .tmp/my_client_website
  Replaced 61 placeholders
  Validation passed — READY TO DEPLOY
```

---

## File Structure

```
.claude/skills/build-website-loveseen/
├── SKILL.md                        ← this file
├── scripts/
│   └── generate_website.py         ← generator script
└── template/
    ├── index.html                  ← parameterized HTML (61 placeholders)
    ├── styles.css                  ← all CSS, no placeholders
    └── assets/
        └── images/
            ├── hero.svg            ← replace with real full-bleed photo
            ├── about.svg           ← replace with real portrait/team photo
            ├── gallery1.svg        ← replace with work samples (larger)
            ├── gallery2.svg        ← replace with work samples
            └── gallery3.svg        ← replace with work samples
```

---

## Image Replacement Tips

The template ships with SVG placeholders. For best results:

| Image | Format | Recommended Size | Notes |
|-------|--------|-----------------|-------|
| `hero.svg` | JPG/WEBP | 1440×900px min | Portrait/close-up works best. High contrast. |
| `about.svg` | JPG/WEBP | 600×750px | Will be shown in a polaroid frame. Square-ish. |
| `gallery1–3.svg` | JPG/WEBP | 800×600px | Work samples, lifestyle shots, behind-the-scenes. |

---

## Preview Server

Port `8085` for template, `8086` for test build 1.

```json
{
  "name": "loveseen-template-preview",
  "runtimeExecutable": "python3",
  "runtimeArgs": ["-m", "http.server", "8085", "--directory", "Website Builder/.claude/skills/build-website-loveseen/template"],
  "port": 8085
}
```

---

## Responsive Breakpoints

| Breakpoint | Behavior |
|-----------|---------|
| `> 1024px` | Desktop: 2-col about, 3-col services, 3-col gallery |
| `≤ 1024px` | Tablet: 1-col about (image first), 2-col gallery |
| `≤ 768px` | Mobile: All single-col, stacked services, NAV CTA hidden |
| `≤ 480px` | Small mobile: Reduced font sizes for logo/headings |

---

## Tested Businesses

| Test | Business | Type |
|------|---------|------|
| 1 | Atelier Léa | Hair & beauty salon (Zürich) |
| 2 | Clara Blume | Wedding photographer (Basel) |

Both generated 61 replacements, validation passed.
