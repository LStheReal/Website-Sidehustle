# Build Website — BiA (Build in Amsterdam) Template

## When to Use

Use this skill when:
- The user asks to **build a website** for a business using **template 2** (BiA / editorial agency style)
- The user wants a premium, editorial-style one-page website for a **professional service business**
- The target business is an architect, consultant, law firm, tax advisor, agency, or similar

**Best for:** Professional service businesses in Switzerland/Europe — agencies, consultancies, architects, law firms, financial advisors, creative studios.

## What It Does

Generates a complete, ready-to-deploy static website from business data using the BiA template:
- Editorial design with serif headings and split-screen layouts
- Gold/amber accent details on dark charcoal hero sections
- 4 numbered service cards, stats section, full contact block
- Responsive across desktop, tablet, and mobile (with hamburger menu)
- German-language UI ("Leistungen", "Über uns", "Kontakt")
- No build step — pure HTML/CSS/JS, works anywhere

## Required Data

Provide a JSON file with these fields:

```json
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
```

### Required Fields
- `BUSINESS_NAME` — Full business name (used in title, footer, alt tags)
- `PHONE` — Phone number (used in contact section and footer)
- `EMAIL` — Email address (used in contact section and footer)

### Auto-Generated Fields
- `BUSINESS_NAME_SHORT` — Auto-generated as first word + "." if not provided
- `META_DESCRIPTION` — Auto-generated from BUSINESS_NAME + TAGLINE if empty

### Optional Fields (have defaults)
All other fields have German-language defaults. See `PLACEHOLDER_DEFAULTS` in generate_website.py for the full list.

## Differences from Template 1 (EarlyDog)

| Feature | EarlyDog (Template 1) | BiA (Template 2) |
|---------|----------------------|-------------------|
| Style | Playful, Bauhaus geometric | Editorial, premium serif |
| Services | 3 service sections | 4 numbered service cards |
| Stats | None | 3 stats with numbers |
| Opening Hours | Not included | Included |
| Hero | 2-column text + illustration | Split-screen image + dark panel |
| CTA | Simple centered heading | Split-screen image + dark panel |
| Mobile menu | Simple link swap | Hamburger + fullscreen overlay |
| Image types | SVG illustrations (shared) | Placeholder SVGs (replace with photos) |
| Placeholders | 20 | 36 |

## How to Run

### From JSON File
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-bia/scripts/generate_website.py \
    --input .tmp/business_data.json \
    --output .tmp/output_website \
    --overwrite
```

### Inline Arguments (limited)
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-bia/scripts/generate_website.py \
    --output .tmp/output_website \
    --business-name "Architekturbüro Weber" \
    --phone "+41 44 123 45 67" \
    --email "info@weber.ch" \
    --overwrite
```

Note: For this template, JSON input is recommended since there are many more content fields than template 1.

## File Structure

```
.claude/skills/build-website-bia/
├── SKILL.md                          ← You are here
├── template/                         ← Reusable template (DO NOT MODIFY)
│   ├── index.html                    ← HTML with {{PLACEHOLDERS}} + mobile menu JS
│   ├── styles.css                    ← Full responsive CSS (4 breakpoints)
│   └── assets/
│       └── images/
│           ├── hero.svg              ← Hero placeholder (replace with photo)
│           ├── showcase.svg          ← Image break placeholder
│           ├── cta.svg               ← CTA section placeholder
│           └── contact.svg           ← Contact section placeholder
└── scripts/
    └── generate_website.py           ← Generation script
```

### Shared Utilities
```
execution/
└── website_utils.py                  ← copy_template(), fill_directory(), validate_output()
```

## Template Design Details

- **Colors**: Cream background (#F5F1EB), dark charcoal sections (#2C2B28), gold accent (#C8944A)
- **Fonts**: Libre Baskerville (serif headings), Inter (sans-serif body) — both Google Fonts
- **Layout**: Full-viewport split-screen hero/CTA, numbered service cards, stats grid
- **Responsive**: 4 breakpoints — desktop (>1024px), tablet (769-1024px), mobile (≤768px), small mobile (≤480px)
- **Mobile**: Hamburger menu → fullscreen overlay, stacked layouts
- **Images**: SVG placeholders included — replace with actual business photos for production

## Image Notes

The template includes SVG placeholder images. For production websites:
- Replace `hero.svg` with a high-quality hero photo (recommended: 800x1000px portrait)
- Replace `showcase.svg` with a wide landscape photo (recommended: 1400x600px)
- Replace `cta.svg` with a secondary photo (recommended: 800x800px square)
- Replace `contact.svg` with an office/location photo (recommended: 600x800px portrait)

## Tips

- **HERO_TITLE_LINE3**: Appears in muted color — use it for the "punchline" word
- **BUSINESS_NAME_SHORT**: Keep it punchy: "Weber.", "Müller.", "Studio." etc.
- **STAT numbers**: Use "15+", "200+", "100%" format — big and impressive
- **SECTION_LABEL_***: Small caps labels above headings — keep to 2-3 words
- **SERVICES_HEADING**: Large serif heading — max 8-10 words for best readability
- **OPENING_HOURS**: Format as "Mo–Fr 08:00–18:00" for Swiss businesses
