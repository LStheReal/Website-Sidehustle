# Build Website — Liveblocks (Modern Dark/Light) Template

## When to Use

Use this skill when:
- The user asks to **build a website** for a business using **template 3** (Liveblocks / modern SaaS-style)
- The user wants a sleek, dark/light website with a tech-forward look
- The target business is a tech company, startup, digital agency, IT services, or modern business

**Best for:** Tech companies, IT services, SaaS businesses, digital agencies, startups, engineering firms, and any business that wants a modern, professional online presence.

## What It Does

Generates a complete, ready-to-deploy static website from business data using the Liveblocks-inspired template:
- Modern dark hero with gradient text accent and glowing background
- Light services section with 6 icon cards in a 3×2 grid
- Dark feature highlight with split-screen text/visual layout
- Light about section with lead text, image, and 3 value cards
- Dark CTA section with gradient glow effect
- Light contact section with 2 action cards (phone + email)
- Dark multi-column footer
- Responsive across desktop, tablet, and mobile (with hamburger menu)
- German-language UI ("Leistungen", "Über uns", "Kontakt")
- No build step — pure HTML/CSS/JS, works anywhere

## Required Data

Provide a JSON file with these fields:

```json
{
    "BUSINESS_NAME": "CyberShield IT Solutions",
    "BUSINESS_NAME_SHORT": "CyberShield",
    "TAGLINE": "IT-Sicherheit & Cloud-Lösungen in Zürich",
    "META_DESCRIPTION": "CyberShield IT Solutions — Ihr Partner für IT-Sicherheit...",
    "SECTION_LABEL_HERO": "IT Security & Cloud",
    "HERO_TITLE_LINE1": "Ihre IT.",
    "HERO_TITLE_LINE2": "Sicher und",
    "HERO_WORD_1": "zukunftsfähig.",
    "HERO_WORD_2": "geschützt.",
    "HERO_WORD_3": "skalierbar.",
    "HERO_WORD_4": "zuverlässig.",
    "HERO_TITLE_LINE3": "zukunftsfähig.",
    "HERO_DESCRIPTION": "CyberShield schützt Ihre Systeme...",
    "CTA_BUTTON_PRIMARY": "Kostenlose Analyse",
    "CTA_BUTTON_SECONDARY": "Unsere Services",
    "TRUST_LABEL": "Warum CyberShield",
    "STAT_1_NUMBER": "15+",
    "STAT_1_LABEL": "Jahre Erfahrung",
    "STAT_2_NUMBER": "300+",
    "STAT_2_LABEL": "Geschützte Firmen",
    "STAT_3_NUMBER": "99.9%",
    "STAT_3_LABEL": "Uptime Garantie",
    "STAT_4_NUMBER": "24/7",
    "STAT_4_LABEL": "Monitoring",
    "SECTION_LABEL_SERVICES": "Unsere Services",
    "SERVICES_HEADING": "Umfassende IT-Lösungen aus einer Hand",
    "SERVICES_DESCRIPTION": "Von der Cyber-Security bis zum Cloud-Management...",
    "SERVICE_1_TITLE": "Cyber Security",
    "SERVICE_1_DESCRIPTION": "Penetrationstests, Firewall-Management...",
    "SERVICE_2_TITLE": "Cloud Migration",
    "SERVICE_2_DESCRIPTION": "Sichere Migration Ihrer Systeme...",
    "SERVICE_3_TITLE": "Managed IT",
    "SERVICE_3_DESCRIPTION": "Proaktives Monitoring und Wartung...",
    "SERVICE_4_TITLE": "Backup & Recovery",
    "SERVICE_4_DESCRIPTION": "Automatisierte Backups und schnelle Wiederherstellung...",
    "SERVICE_5_TITLE": "Netzwerk & VPN",
    "SERVICE_5_DESCRIPTION": "Sichere Netzwerkarchitektur und VPN-Lösungen...",
    "SERVICE_6_TITLE": "Compliance",
    "SERVICE_6_DESCRIPTION": "DSGVO, ISO 27001 und branchenspezifische Beratung...",
    "SECTION_LABEL_FEATURE": "Unser Ansatz",
    "FEATURE_HEADING": "Proaktiver Schutz statt reaktiver Schadensbegrenzung",
    "FEATURE_DESCRIPTION": "Unser Security Operations Center überwacht...",
    "FEATURE_POINT_1": "24/7 Security Monitoring mit KI-gestützter Bedrohungserkennung",
    "FEATURE_POINT_2": "Monatliche Sicherheitsberichte und Schwachstellenanalysen",
    "FEATURE_POINT_3": "Dedizierter Security Engineer als fester Ansprechpartner",
    "SECTION_LABEL_ABOUT": "Über CyberShield",
    "ABOUT_HEADING": "Sicherheit ist unsere Mission",
    "ABOUT_LEAD": "Gegründet 2009 in Zürich, sind wir heute...",
    "ABOUT_DESCRIPTION": "Unser Team aus zertifizierten Security-Experten...",
    "VALUE_1_TITLE": "Swiss Quality",
    "VALUE_1_DESCRIPTION": "Alle Daten bleiben in der Schweiz...",
    "VALUE_2_TITLE": "Zertifiziert",
    "VALUE_2_DESCRIPTION": "ISO 27001 zertifiziert...",
    "VALUE_3_TITLE": "Partnerschaftlich",
    "VALUE_3_DESCRIPTION": "Wir arbeiten als Erweiterung Ihres Teams...",
    "CTA_HEADING_LINE1": "IT-Sicherheit",
    "CTA_HEADING_LINE2": "beginnt heute.",
    "CTA_DESCRIPTION": "Vereinbaren Sie eine kostenlose Sicherheitsanalyse...",
    "CONTACT_CARD_1_TITLE": "Beratungsgespräch",
    "CONTACT_CARD_1_DESCRIPTION": "Sprechen Sie mit einem unserer Security-Experten...",
    "CONTACT_CARD_2_TITLE": "Anfrage senden",
    "CONTACT_CARD_2_DESCRIPTION": "Beschreiben Sie Ihre Anforderungen...",
    "PHONE": "+41 44 555 66 77",
    "PHONE_SHORT": "+41 44 555 66 77",
    "EMAIL": "info@cybershield.ch",
    "ADDRESS": "Technoparkstrasse 1, 8005 Zürich",
    "OPENING_HOURS": "Mo–Fr 08:00–18:00, Notfall 24/7",
    "FOOTER_COL_1_TITLE": "Services",
    "FOOTER_COL_1_LINK_1": "Cyber Security",
    "FOOTER_COL_1_LINK_2": "Cloud Migration",
    "FOOTER_COL_1_LINK_3": "Managed IT",
    "FOOTER_COL_2_TITLE": "Unternehmen",
    "FOOTER_COL_2_LINK_1": "Über uns",
    "FOOTER_COL_2_LINK_2": "Kontakt",
    "FOOTER_COL_2_LINK_3": "Karriere"
}
```

### Required Fields
- `BUSINESS_NAME` — Full business name (used in title, footer, alt tags)
- `PHONE` — Phone number (used in contact section and footer)
- `EMAIL` — Email address (used in contact section and footer)

### Auto-Generated Fields
- `BUSINESS_NAME_SHORT` — Auto-generated as first word if not provided
- `PHONE_SHORT` — Defaults to same as PHONE if not provided
- `META_DESCRIPTION` — Auto-generated from BUSINESS_NAME + TAGLINE if empty
- `FOOTER_COL_1_LINK_*` — Auto-populated from SERVICE_*_TITLE if not provided

### Optional Fields (have defaults)
All other fields have German-language defaults. See `PLACEHOLDER_DEFAULTS` in generate_website.py for the full list.

## Differences from Other Templates

| Feature | EarlyDog (Template 1) | BiA (Template 2) | Liveblocks (Template 3) |
|---------|----------------------|-------------------|------------------------|
| Style | Playful, Bauhaus | Editorial serif | Modern dark/light SaaS |
| Services | 3 service sections | 4 numbered cards | 6 icon cards (3×2 grid) |
| Stats | None | 3 stats | 4 stats in trust bar |
| Values | None | None | 3 value cards |
| Feature section | None | None | Split-screen highlight |
| Hero | 2-col text + illustration | Split-screen image + dark | Full-dark with gradient glow |
| CTA | Simple centered | Split-screen image + dark | Dark with gradient glow |
| Footer | Simple 2-col | Simple 3-col | Multi-column dark footer |
| Contact cards | None | None | 2 action cards (phone/email) |
| Mobile menu | Link swap | Hamburger overlay | Hamburger overlay |
| Placeholders | 20 | 36 | 71 |

## How to Run

### From JSON File
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-liveblocks/scripts/generate_website.py \
    --input .tmp/business_data.json \
    --output .tmp/output_website \
    --overwrite
```

### Inline Arguments (limited)
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-liveblocks/scripts/generate_website.py \
    --output .tmp/output_website \
    --business-name "CyberShield IT Solutions" \
    --phone "+41 44 555 66 77" \
    --email "info@cybershield.ch" \
    --overwrite
```

Note: For this template, JSON input is strongly recommended since there are 71 content fields. Inline arguments only cover the basics.

## File Structure

```
.claude/skills/build-website-liveblocks/
├── SKILL.md                          ← You are here
├── template/                         ← Reusable template (DO NOT MODIFY)
│   ├── index.html                    ← HTML with {{PLACEHOLDERS}} + mobile menu JS + scroll nav
│   ├── styles.css                    ← Full responsive CSS (4 breakpoints)
│   └── assets/
│       └── images/
│           ├── feature.svg           ← Feature section visual (terminal-like)
│           └── about.svg             ← About section placeholder
└── scripts/
    └── generate_website.py           ← Generation script
```

### Shared Utilities
```
execution/
└── website_utils.py                  ← copy_template(), fill_directory(), validate_output()
```

## Template Design Details

- **Colors**: Dark bg (#0A0A0A), light sections (#FAFAFA/#FFFFFF), accent pink (#E04EC4), gradient text (pink → purple)
- **Fonts**: Inter (Google Fonts) — clean sans-serif for everything
- **Layout**: Full-width alternating dark/light sections, centered content, card grids
- **Responsive**: 4 breakpoints — desktop (>1024px), tablet (769-1024px), mobile (≤768px), small mobile (≤480px)
- **Mobile**: Hamburger menu → fullscreen overlay, stacked layouts, full-width buttons
- **Nav**: Fixed top navigation with blur backdrop on scroll
- **Special effects**: Gradient glow on hero and CTA backgrounds, **typewriter animation** on hero (cycles 4 words with typing cursor)

## Image Notes

The template includes SVG placeholder images. For production websites:
- Replace `feature.svg` with a product screenshot or code/dashboard visual (recommended: 600x400px)
- Replace `about.svg` with a team photo or office image (recommended: 600x450px)
- SVG icons in service cards are inline and don't need replacement

## Section Overview

1. **Hero** (dark) — Full-viewport centered headline with **typing animation** (4 rotating words in gradient), label pill, description, 2 buttons
2. **Trust Bar** (dark) — 4 stat numbers in a row with labels
3. **Services** (light) — Section header + 6 icon cards in 3×2 grid
4. **Feature Highlight** (dark) — Split-screen: text with bullet points + visual image
5. **About** (light) — Header + 2-col text/image + 3 value cards
6. **CTA** (dark) — Centered headline + description + 2 buttons with gradient glow
7. **Contact** (light) — 2 action cards + address/hours details
8. **Footer** (dark) — Logo + 3 link columns + copyright bar

## Tips

- **HERO_WORD_1 to HERO_WORD_4**: These 4 words rotate with a typing animation on the hero — use short punchline words (1-2 words each) that show what the business delivers. e.g. "zukunftsfähig.", "geschützt.", "skalierbar.", "zuverlässig."
- **STAT numbers**: Keep them short: "15+", "24/7", "99.9%", "2'500+"
- **SERVICE_*_TITLE**: Max 2-3 words for best card layout
- **FEATURE_POINT_***: One line each, ~50-70 characters
- **CTA_HEADING_LINE1/LINE2**: Split across 2 lines for impact
- **CONTACT_CARD_***: One for phone calls, one for email — customize titles and descriptions
- **FOOTER_COL_1_LINK_***: Auto-populated from service titles if not set manually
- **PHONE_SHORT**: Use if you want an abbreviated display in the nav (e.g., "044 555 66 77")
