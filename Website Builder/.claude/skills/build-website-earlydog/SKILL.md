# Build Website — EarlyDog Template

## When to Use

Use this skill when:
- The user asks to **build a website** for a business using **template 1** (earlydog / clean service business)
- The user wants a simple, professional one-page website for a **local service business**
- The target business is a cleaner, plumber, electrician, hairdresser, or similar trade

**Best for:** Small local businesses in Switzerland/Europe with 2-4 core services.

## What It Does

Generates a complete, ready-to-deploy static website from business data using the earlydog template:
- Clean, modern one-page design (Bauhaus-inspired geometric illustrations)
- Responsive across desktop, tablet, and mobile
- Hero section + 3 service sections + CTA + footer
- German-language UI ("Kontakt", "Kontaktieren Sie uns")
- No build step — pure HTML/CSS, works anywhere

## Required Data

Provide a JSON file with these fields:

```json
{
    "BUSINESS_NAME": "Swiss Textilreinigung",
    "TAGLINE": "Professionelle Textilreinigung in Dietikon",
    "META_DESCRIPTION": "Swiss Textilreinigung bietet professionelle Reinigung...",
    "HERO_TITLE_LINE1": "Professionelle",
    "HERO_TITLE_LINE2": "Textilreinigung",
    "HERO_DESCRIPTION": "Seit über 20 Jahren Ihr Partner für saubere Textilien...",
    "SERVICE_1_TITLE": "Textilreinigung",
    "SERVICE_1_DESCRIPTION": "Professionelle Reinigung aller Textilien...",
    "SERVICE_1_CTA": "Mehr erfahren",
    "SERVICE_2_TITLE": "Hemdenservice",
    "SERVICE_2_DESCRIPTION": "Perfekt gebügelte Hemden...",
    "SERVICE_2_CTA": "Jetzt anfragen",
    "SERVICE_3_TITLE": "Expressreinigung",
    "SERVICE_3_DESCRIPTION": "Heute abgeben, morgen abholen...",
    "SERVICE_3_CTA": "Express buchen",
    "CTA_TITLE_LINE1": "Interesse geweckt?",
    "CTA_TITLE_LINE2": "Kontaktieren Sie uns.",
    "PHONE": "+41 44 740 13 62",
    "EMAIL": "info@swisstextil.ch",
    "ADDRESS": "Steinmürlistrasse 38, 8953 Dietikon"
}
```

### Required Fields
- `BUSINESS_NAME` — Used in nav, title tag, footer copyright
- `PHONE` — Used in CTA button link and footer
- `EMAIL` — Used in footer

### Optional Fields (have defaults)
- `TAGLINE` → defaults to "Ihr Partner vor Ort"
- `META_DESCRIPTION` → auto-generated from BUSINESS_NAME + TAGLINE if empty
- `HERO_TITLE_LINE1` → "Willkommen bei"
- `HERO_TITLE_LINE2` → "unserem Service"
- `HERO_DESCRIPTION` → generic description
- `SERVICE_*_TITLE/DESCRIPTION` → generic service placeholders
- `SERVICE_*_CTA` → "Mehr erfahren"
- `CTA_TITLE_LINE1` → "Interesse geweckt?"
- `CTA_TITLE_LINE2` → "Kontaktieren Sie uns."
- `ADDRESS` → empty

## How to Run

### Option 1: From JSON File
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-earlydog/scripts/generate_website.py \
    --input .tmp/business_data.json \
    --output .tmp/output_website \
    --overwrite
```

### Option 2: Inline Arguments
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-earlydog/scripts/generate_website.py \
    --output .tmp/output_website \
    --business-name "Swiss Textilreinigung" \
    --phone "+41 44 740 13 62" \
    --email "info@swisstextil.ch" \
    --address "Steinmürlistrasse 38, 8953 Dietikon" \
    --hero-title-1 "Professionelle" \
    --hero-title-2 "Textilreinigung" \
    --overwrite
```

### Option 3: Agent Workflow (Recommended)

When building a website for a lead from the Google Sheet:

1. **Get business data** from Google Sheets (from scraping skill output)
2. **Create the data JSON** with all required fields
3. **Run the generation script** as shown above
4. **Preview the result** using the `generated-preview` server config
5. **Deploy** to hosting (Netlify)

## File Structure

```
.claude/skills/build-website-earlydog/
├── SKILL.md                          ← You are here
├── template/                         ← Reusable template (DO NOT MODIFY)
│   ├── index.html                    ← HTML with {{PLACEHOLDERS}}
│   ├── styles.css                    ← Full responsive CSS
│   └── assets/
│       └── images/
│           ├── hero.svg              ← Bauhaus hero illustration
│           ├── section1.svg          ← Service 1 illustration
│           ├── section2.svg          ← Service 2 illustration
│           └── section3.svg          ← Service 3 illustration
└── scripts/
    └── generate_website.py           ← Generation script
```

### Shared Utilities
```
execution/
└── website_utils.py                  ← copy_template(), fill_directory(), validate_output()
```

## Template Design Details

- **Colors**: Cream background (#FFF9F0), dark text (#000609), blue accent (#0A65DB)
- **Font**: Plus Jakarta Sans (Google Fonts)
- **Layout**: Fixed vertical nav left (desktop), 2-column grids with alternating image/text
- **Responsive**: 4 breakpoints — desktop (>1024px), tablet (769-1024px), mobile (≤768px), small mobile (≤480px)
- **Illustrations**: 4 Bauhaus-style geometric SVGs (shared across all generated sites)

## Validation

The script automatically validates that all placeholders were replaced. Output includes:
- `READY TO DEPLOY` — all placeholders filled ✓
- `NEEDS REVIEW` — some placeholders remain (lists which ones)

## Preview

To preview a generated website locally:
1. The `generated-preview` server config in `.claude/launch.json` points to `.tmp/test_website`
2. Update the directory path if your output is elsewhere
3. Or use: `python3 -m http.server 8081 --directory <output-dir>`

## Deployment

After generation, deploy the output directory to Netlify:
```bash
netlify deploy --prod --dir=.tmp/output_website
```
(Netlify CLI setup documented in execution/deploy.py — coming soon)

## Tips

- **HERO_TITLE_LINE1/LINE2**: Keep short (1-2 words each). LINE2 appears in blue.
- **SERVICE descriptions**: 1-2 sentences max. Clean and concise works best.
- **CTA buttons**: "Mehr erfahren", "Jetzt anfragen", "Termin buchen" are good options.
- **Phone format**: Use international format with spaces: "+41 44 740 13 62"
- The template uses German language for UI elements. For French/Italian businesses, update the template nav/CTA text.
