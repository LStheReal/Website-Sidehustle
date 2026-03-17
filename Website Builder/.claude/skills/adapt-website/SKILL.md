# Adapt Website — Customize Template with Customer Input

## When to Use

Use this skill when:
- A customer has **chosen a template** and provided their **customization input** (description, values, logo, images)
- Pipeline Step 7: "Build Final" — refine the chosen template with real customer content
- The order has been submitted via the dashboard and you need to build the final website

**NOT for:** Initial draft builds (use `build-website-earlydog/bia/liveblocks/loveseen` instead). This skill adapts an already-chosen template with the customer's own content.

## What It Does

Takes a template + business data + customer input and creates a fully customized website where:
- **ALL text** is rewritten by you (Claude) to be tailored, natural, and specific to this business
- **Images** are intelligently placed — you decide which uploaded image fits best in each section
- **Logo** is injected into the navigation and footer
- The template HTML/CSS structure stays unchanged

## Required Input

You need:
1. **`lead_id`** — 12-char hex ID to fetch business data from Google Sheet
2. **`template_key`** — one of: `earlydog`, `bia`, `liveblocks`, `loveseen`
3. **Customer description** — free text describing their business (from dashboard Step 3)
4. **Customer values/highlights** — comma-separated strengths (from dashboard Step 3)
5. **Logo file path** — customer's logo image
6. **Image file paths** — customer's photos (team, workspace, products, etc.)

Typically this data comes from the `notes` JSON field in the Google Sheet (written by the dashboard order endpoint) and the Google Drive folder for uploaded files.

## Process

### Step 1: Fetch Business Data

```bash
# The lead data is in the Google Sheet
# Read using the existing google_auth + gspread pattern
```

From the sheet you get: `business_name`, `category`, `city`, `phone`, `owner_email`, `address`, `chosen_template`, `notes` (JSON with description, values, drive_folder URL).

### Step 2: Read the Template's Placeholder List

Each template has different placeholders. Read the chosen template's SKILL.md to see what content you need to generate.

**Placeholder counts:**
- `earlydog` — 20 placeholders (simplest)
- `bia` — 36 placeholders
- `loveseen` — 45 placeholders
- `liveblocks` — 71 placeholders (most complex)

### Step 3: Generate ALL Content

This is the core of this skill. You (Claude) write every single text field for the website.

**Rules:**
- All text in **German** (Swiss market, "Schweizerdeutsch-freundlich" but Hochdeutsch)
- Adapt tone to the business type (law firm = formal, hair salon = friendly, tech startup = modern)
- Use the customer's description as the primary source — don't invent facts
- Parse values/highlights into stats, feature points, and selling propositions
- Keep text concise — website copy, not essays
- Hero titles: max 3-4 words per line, punchy
- Service descriptions: 1-2 sentences each
- Stats: use "15+", "500+", "100%" format

**Generate a complete `business_data.json`** with ALL placeholder keys filled. Example for BiA:

```json
{
    "BUSINESS_NAME": "Diamant Falke Nagelstudio",
    "BUSINESS_NAME_SHORT": "Diamant.",
    "TAGLINE": "Ihr Nagelstudio in Luzern",
    "META_DESCRIPTION": "Diamant Falke — Exklusives Nagelstudio für Gel-Nägel und Maniküre in Luzern",
    "SECTION_LABEL_HERO": "Nagelkunst & Pflege",
    "HERO_TITLE_LINE1": "Perfektion",
    "HERO_TITLE_LINE2": "bis in die",
    "HERO_TITLE_LINE3": "Fingerspitzen.",
    "INTRO_TEXT": "Willkommen bei Diamant Falke",
    "INTRO_DESCRIPTION": "Seit 2018 verwöhnen wir unsere Kundinnen...",
    ...
}
```

### Step 4: Build the Website

```bash
source .venv/bin/activate
python3 .claude/skills/build-website-{template_key}/scripts/generate_website.py \
    --input .tmp/business_data.json \
    --output .tmp/adapted_website \
    --overwrite
```

### Step 5: Replace Images (Intelligent Placement)

**This is where you make image decisions.** Analyze the uploaded images and decide which one fits best in each template slot.

**Template image slots:**

| Template | Slots |
|----------|-------|
| earlydog | `hero`, `section1`, `section2`, `section3` |
| bia | `hero`, `showcase`, `cta`, `contact` |
| liveblocks | `feature`, `about` |
| loveseen | `hero`, `about`, `gallery1`, `gallery2`, `gallery3` |

**How to decide placement:**
- Look at image filenames for hints (e.g. "team.jpg" → about/hero, "work-sample.jpg" → gallery/showcase)
- Consider the business type — a nail salon's "work" photos go in gallery, a consultant's "office" goes in hero
- Hero = most impressive/wide photo
- About = team or portrait photo
- Gallery = work samples, portfolio pieces
- If fewer images than slots, leave remaining SVGs as-is

Run the script:
```bash
python3 .claude/skills/adapt-website/scripts/replace_images.py \
    --website-dir .tmp/adapted_website \
    --logo /path/to/logo.png \
    --images /path/to/photo1.jpg /path/to/photo2.jpg \
    --template-key bia \
    --placement '{"hero": "photo1.jpg", "showcase": "photo2.jpg"}'
```

### Step 6: Validate

Check the output:
```bash
grep -r "{{" .tmp/adapted_website/index.html
```
Should return nothing. If placeholders remain, fill them manually.

### Step 7: Output

The final website is in `.tmp/adapted_website/` — ready for `deploy-website` skill.

Update the Google Sheet:
- `status` → `"website_ready"`
- `notes` → append `"adapted": true, "adapted_date": "2024-..."` to the JSON

## Placeholder Reference

### earlydog (20 keys)
`BUSINESS_NAME`, `TAGLINE`, `META_DESCRIPTION`, `HERO_TITLE_LINE1`, `HERO_TITLE_LINE2`, `HERO_DESCRIPTION`, `SERVICE_1_TITLE`, `SERVICE_1_DESCRIPTION`, `SERVICE_1_CTA`, `SERVICE_2_TITLE`, `SERVICE_2_DESCRIPTION`, `SERVICE_2_CTA`, `SERVICE_3_TITLE`, `SERVICE_3_DESCRIPTION`, `SERVICE_3_CTA`, `CTA_TITLE_LINE1`, `CTA_TITLE_LINE2`, `PHONE`, `EMAIL`, `ADDRESS`

### bia (36 keys)
`BUSINESS_NAME`, `BUSINESS_NAME_SHORT`, `TAGLINE`, `META_DESCRIPTION`, `SECTION_LABEL_HERO`, `HERO_TITLE_LINE1`, `HERO_TITLE_LINE2`, `HERO_TITLE_LINE3`, `INTRO_TEXT`, `INTRO_DESCRIPTION`, `SECTION_LABEL_SERVICES`, `SERVICES_HEADING`, `SERVICE_1_TITLE`, `SERVICE_1_DESCRIPTION`, `SERVICE_2_TITLE`, `SERVICE_2_DESCRIPTION`, `SERVICE_3_TITLE`, `SERVICE_3_DESCRIPTION`, `SERVICE_4_TITLE`, `SERVICE_4_DESCRIPTION`, `SECTION_LABEL_ABOUT`, `ABOUT_HEADING`, `ABOUT_DESCRIPTION`, `STAT_1_NUMBER`, `STAT_1_LABEL`, `STAT_2_NUMBER`, `STAT_2_LABEL`, `STAT_3_NUMBER`, `STAT_3_LABEL`, `CTA_TITLE_LINE1`, `CTA_TITLE_LINE2`, `CTA_TITLE_LINE3`, `PHONE`, `EMAIL`, `ADDRESS`, `OPENING_HOURS`

### liveblocks (71 keys)
`BUSINESS_NAME`, `BUSINESS_NAME_SHORT`, `TAGLINE`, `META_DESCRIPTION`, `SECTION_LABEL_HERO`, `HERO_TITLE_LINE1`, `HERO_TITLE_LINE2`, `HERO_WORD_1`, `HERO_WORD_2`, `HERO_WORD_3`, `HERO_WORD_4`, `HERO_DESCRIPTION`, `CTA_BUTTON_PRIMARY`, `CTA_BUTTON_SECONDARY`, `TRUST_LABEL`, `STAT_1_NUMBER`, `STAT_1_LABEL`, `STAT_2_NUMBER`, `STAT_2_LABEL`, `STAT_3_NUMBER`, `STAT_3_LABEL`, `STAT_4_NUMBER`, `STAT_4_LABEL`, `SECTION_LABEL_SERVICES`, `SERVICES_HEADING`, `SERVICES_DESCRIPTION`, `SERVICE_1_TITLE`, `SERVICE_1_DESCRIPTION`, `SERVICE_2_TITLE`, `SERVICE_2_DESCRIPTION`, `SERVICE_3_TITLE`, `SERVICE_3_DESCRIPTION`, `SERVICE_4_TITLE`, `SERVICE_4_DESCRIPTION`, `SERVICE_5_TITLE`, `SERVICE_5_DESCRIPTION`, `SERVICE_6_TITLE`, `SERVICE_6_DESCRIPTION`, `SECTION_LABEL_FEATURE`, `FEATURE_HEADING`, `FEATURE_DESCRIPTION`, `FEATURE_POINT_1`, `FEATURE_POINT_2`, `FEATURE_POINT_3`, `SECTION_LABEL_ABOUT`, `ABOUT_HEADING`, `ABOUT_LEAD`, `ABOUT_DESCRIPTION`, `VALUE_1_TITLE`, `VALUE_1_DESCRIPTION`, `VALUE_2_TITLE`, `VALUE_2_DESCRIPTION`, `VALUE_3_TITLE`, `VALUE_3_DESCRIPTION`, `CTA_HEADING_LINE1`, `CTA_HEADING_LINE2`, `CTA_DESCRIPTION`, `CONTACT_CARD_1_TITLE`, `CONTACT_CARD_1_DESCRIPTION`, `CONTACT_CARD_2_TITLE`, `CONTACT_CARD_2_DESCRIPTION`, `PHONE`, `PHONE_SHORT`, `EMAIL`, `ADDRESS`, `OPENING_HOURS`, `FOOTER_COL_1_TITLE`, `FOOTER_COL_1_LINK_1`, `FOOTER_COL_1_LINK_2`, `FOOTER_COL_1_LINK_3`, `FOOTER_COL_2_TITLE`, `FOOTER_COL_2_LINK_1`, `FOOTER_COL_2_LINK_2`, `FOOTER_COL_2_LINK_3`

### loveseen (45 keys)
`BUSINESS_NAME`, `TAGLINE`, `META_DESCRIPTION`, `NAV_CTA`, `NAV_LINK_1`, `NAV_LINK_2`, `NAV_LINK_3`, `NAV_LINK_4`, `HERO_TITLE_LINE1`, `HERO_TITLE_LINE2`, `HERO_CTA`, `SECTION_LABEL_ABOUT`, `ABOUT_HEADING_LINE1`, `ABOUT_HEADING_LINE2`, `ABOUT_LEAD`, `ABOUT_DESCRIPTION`, `ABOUT_CTA`, `STATEMENT_LABEL`, `STATEMENT_LINE1`, `STATEMENT_LINE2`, `STATEMENT_LINE3`, `SECTION_LABEL_SERVICES`, `SERVICES_HEADING`, `SERVICE_1_TITLE`, `SERVICE_1_DESCRIPTION`, `SERVICE_2_TITLE`, `SERVICE_2_DESCRIPTION`, `SERVICE_3_TITLE`, `SERVICE_3_DESCRIPTION`, `SERVICES_CTA`, `GALLERY_LABEL`, `INSTAGRAM_HANDLE`, `INSTAGRAM_URL`, `CONTACT_TAGLINE`, `EMAIL_PLACEHOLDER`, `CONTACT_LABEL_PHONE`, `CONTACT_LABEL_EMAIL`, `CONTACT_LABEL_ADDRESS`, `CONTACT_LABEL_HOURS`, `PHONE`, `EMAIL`, `ADDRESS`, `OPENING_HOURS`, `FOOTER_PRIVACY`, `FOOTER_TERMS`, `FOOTER_YEAR`

## Tips for Content Generation

- **Hero titles**: Think billboard — short, impactful. "Perfektion / bis in die / Fingerspitzen." not "Wir bieten professionelle Dienstleistungen an."
- **BUSINESS_NAME_SHORT**: First meaningful word + period. "Diamant.", "Weber.", "Studio."
- **Stats**: Parse customer values. "20 Jahre Erfahrung, 500 Kunden" → `STAT_1_NUMBER: "20+", STAT_1_LABEL: "Jahre Erfahrung"`, `STAT_2_NUMBER: "500+", STAT_2_LABEL: "Zufriedene Kunden"`
- **Services**: Infer from business category + description. A "Malergeschäft" gets "Fassadenmalerei", "Innenräume", "Renovationen". Don't use generic "Beratung", "Umsetzung".
- **CTAs**: Match the business. "Termin vereinbaren" for salon, "Offerte anfordern" for trades, "Kontakt aufnehmen" for consulting.
- **Section labels**: 2-3 words. "Nagel-Kunst & Pflege", not "Unsere Dienstleistungen im Bereich der Nagelpflege".
