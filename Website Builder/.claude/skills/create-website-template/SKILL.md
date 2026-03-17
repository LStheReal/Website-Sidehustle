# Create Website Template — Meta-Skill

## When to Use

Use this skill when the user provides a **reference website URL** (or scraped data of one) and asks you to create a new website template skill from it. This is the process for turning any design inspiration into a reusable, deployment-ready template.

## What It Does

Takes a reference website and produces:
1. A complete **template skill** in `.claude/skills/build-website-{name}/`
2. A parameterized **HTML/CSS template** with `{{PLACEHOLDERS}}`
3. A **generate_website.py** script that fills placeholders from business data
4. A **SKILL.md** documenting the template, data schema, and usage
5. **2 test websites** generated with different business data to verify everything works

## The 7-Step Workflow

### Step 1 — Study the Reference Site
**Goal:** Understand the design system — layout, colors, fonts, sections, responsive behavior.

**Actions:**
1. Check scraped data in `~/Documents/website-cloner/Websites Datasets/dataset_{domain}/`
   - `screenshots/` — Visual reference for each page
   - `html/` — Source HTML (often minified for SPAs)
   - `assets/` — CSS files, fonts, images, SVGs
2. From CSS files, extract:
   - **Font families** (find Google Fonts alternatives for licensed fonts)
   - **Color palette** (hex codes for background, text, accent, dark sections)
   - **Spacing/layout patterns** (grid systems, padding values)
3. From screenshots, identify:
   - **Page sections** (hero, services, about, contact, CTA, footer)
   - **Layout patterns** (split-screen, grid cards, full-width images)
   - **Unique design elements** (accent shapes, numbered items, decorative dots)
4. Decide what to keep and what to adapt for a generic business template

**Font alternatives cheat sheet:**
| Licensed Font | Google Fonts Alternative |
|--------------|------------------------|
| Neue Haas Grotesk | Inter |
| Helvetica Neue | Inter or DM Sans |
| Reckless Neue | Libre Baskerville or Playfair Display |
| Usual (Typekit) | Plus Jakarta Sans |
| Futura | Poppins or Jost |
| Avenir | Nunito Sans |
| Circular | DM Sans or Plus Jakarta Sans |

### Step 2 — Create the Skill Directory Structure

```bash
mkdir -p .claude/skills/build-website-{name}/template/assets/images
mkdir -p .claude/skills/build-website-{name}/scripts
```

### Step 3 — Build the Template HTML

Create `template/index.html` with:
- Semantic HTML5 structure (`nav`, `main`, `section`, `footer`)
- All text content as `{{PLACEHOLDER}}` markers (UPPERCASE_SNAKE_CASE)
- Google Fonts `<link>` in `<head>`
- Proper `<meta>` tags with placeholders for SEO
- Links: `href="tel:{{PHONE}}"`, `href="mailto:{{EMAIL}}"`, `href="#section-id"`
- Images: `src="assets/images/name.svg"` with `alt="{{BUSINESS_NAME}}"`
- Mobile menu JS inline (if hamburger menu needed)

**Placeholder naming convention:**
- `{{BUSINESS_NAME}}` — Full business name
- `{{BUSINESS_NAME_SHORT}}` — Abbreviated (if template uses a short logo)
- `{{TAGLINE}}` — Subtitle/tagline
- `{{META_DESCRIPTION}}` — SEO description
- `{{HERO_TITLE_LINE1}}` / `{{HERO_TITLE_LINE2}}` — Hero heading lines
- `{{SERVICE_N_TITLE}}` / `{{SERVICE_N_DESCRIPTION}}` — Service items
- `{{SECTION_LABEL_*}}` — Small section labels
- `{{STAT_N_NUMBER}}` / `{{STAT_N_LABEL}}` — Statistics
- `{{CTA_TITLE_LINE1}}` etc. — Call-to-action heading
- `{{PHONE}}`, `{{EMAIL}}`, `{{ADDRESS}}`, `{{OPENING_HOURS}}` — Contact info

### Step 4 — Build the Template CSS

Create `template/styles.css` with:
- CSS custom properties (`:root { --color-bg: ...; --font-serif: ...; }`)
- Reset + base styles
- Typography system (headings serif, body sans-serif, section labels uppercase)
- Each section styled to match the reference
- **4 responsive breakpoints:**
  - Desktop: `> 1024px` (default)
  - Tablet: `@media (max-width: 1024px)`
  - Mobile: `@media (max-width: 768px)`
  - Small mobile: `@media (max-width: 480px)`

### Step 5 — Screenshot Loop Verification

**This is critical.** Use the preview server to verify the template pixel by pixel.

1. Add a server config to `.claude/launch.json`:
```json
{
  "name": "{name}-template-preview",
  "runtimeExecutable": "python3",
  "runtimeArgs": ["-m", "http.server", "{port}", "--directory", ".claude/skills/build-website-{name}/template"],
  "port": {port}
}
```

2. Start the preview server: `preview_start`
3. Resize to desktop (1280x900): `preview_resize`
4. Take screenshot: `preview_screenshot`
5. Compare against reference screenshots — fix CSS issues
6. Scroll through all sections: `preview_eval` with `window.scrollTo()`
7. Test mobile (375x812): `preview_resize` to mobile preset
8. Test tablet (900x1024): custom `preview_resize`
9. Verify footer, nav, all sections at each breakpoint
10. Use `preview_snapshot` (accessibility tree) to verify content structure

**Scroll tip:** If smooth scroll blocks `window.scrollTo()`, disable it first:
```js
document.documentElement.style.scrollBehavior = 'auto';
window.scrollTo({top: 2000, behavior: 'instant'});
```

### Step 6 — Build the Generation Script

Create `scripts/generate_website.py` following this exact pattern:

```python
#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from execution.website_utils import copy_template, fill_directory, validate_output

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"

PLACEHOLDER_DEFAULTS = {
    "BUSINESS_NAME": "Unser Unternehmen",
    # ... all placeholders with German defaults ...
}

def merge_with_defaults(data: dict) -> dict:
    merged = dict(PLACEHOLDER_DEFAULTS)
    for key, value in data.items():
        if value is not None:
            merged[key] = value
    # Auto-generate META_DESCRIPTION if empty
    if not merged.get("META_DESCRIPTION"):
        name = merged.get("BUSINESS_NAME", "")
        tagline = merged.get("TAGLINE", "")
        merged["META_DESCRIPTION"] = f"{name} — {tagline}" if tagline else name
    return merged

def generate_website(data, output_dir, overwrite=False):
    merged = merge_with_defaults(data)
    output_path = copy_template(str(TEMPLATE_DIR), output_dir, overwrite=overwrite)
    replacements = fill_directory(output_path, merged)
    validation = validate_output(output_path)
    return {"output_dir": output_path, "validation": validation}
```

**Key rules:**
- `PROJECT_ROOT = Path(__file__).resolve().parents[4]` — always 4 levels up from `scripts/generate_website.py`
- Import shared utils from `execution.website_utils`
- Every placeholder in the HTML must have a default in `PLACEHOLDER_DEFAULTS`
- Auto-generate `META_DESCRIPTION` and `BUSINESS_NAME_SHORT` if missing
- CLI supports both `--input data.json` and inline `--business-name` args

### Step 7 — Test with 2 Businesses & Write SKILL.md

1. **Create 2 test JSON files** in `.tmp/` with completely different businesses:
   - Test 1: A business that fits the template perfectly
   - Test 2: A different type of business to test flexibility

2. **Run the generation script** for both:
```bash
source .venv/bin/activate
python3 .claude/skills/build-website-{name}/scripts/generate_website.py \
    --input .tmp/test_{name}_1.json --output .tmp/test_{name}_website_1 --overwrite
python3 .claude/skills/build-website-{name}/scripts/generate_website.py \
    --input .tmp/test_{name}_2.json --output .tmp/test_{name}_website_2 --overwrite
```

3. **Verify both pass:** "Replaced X placeholders... Validation passed... READY TO DEPLOY"

4. **Preview the generated site** to confirm real content renders correctly:
   - Use `preview_snapshot` to verify all placeholders were replaced with real text
   - Use `preview_screenshot` at desktop width to verify visual appearance

5. **Write SKILL.md** with:
   - When to use (what type of business)
   - Full JSON data schema with example
   - Required vs optional fields
   - How to run (CLI commands)
   - File structure
   - Design details (colors, fonts, layout)
   - Tips for best results

## Shared Infrastructure

All template skills share these utilities:

### `execution/website_utils.py`
- `copy_template(template_dir, output_dir)` — Copy template to output
- `fill_directory(directory, data)` — Replace all `{{PLACEHOLDERS}}` in HTML/CSS/JS
- `validate_output(directory)` — Check no unfilled placeholders remain

### `.claude/launch.json`
Dev server configs for previewing templates. Each template gets its own port:
- Template 1 (earlydog): port 8080
- Template 2 (bia): port 8082
- Template 3+: port 8083, 8084, etc.

## Quality Checklist

Before a template skill is complete, verify:

- [ ] Desktop layout matches reference design (1280px)
- [ ] Mobile layout is fully responsive (375px)
- [ ] Tablet layout works (900px)
- [ ] All placeholder text uses `{{UPPERCASE_SNAKE_CASE}}`
- [ ] HTML has proper `<meta>` tags with placeholders
- [ ] CSS uses custom properties (`:root`)
- [ ] CSS has 4 responsive breakpoints
- [ ] Images are SVG placeholders (or copied from reference)
- [ ] `generate_website.py` uses shared `website_utils.py`
- [ ] All placeholders have German defaults in `PLACEHOLDER_DEFAULTS`
- [ ] `META_DESCRIPTION` auto-generates if empty
- [ ] Test 1 passes: all placeholders filled, READY TO DEPLOY
- [ ] Test 2 passes: all placeholders filled, READY TO DEPLOY
- [ ] `SKILL.md` documents data schema, usage, design details
- [ ] Output is pure static HTML/CSS/JS — no build step needed

## Existing Templates

| Template | Skill Name | Style | Best For | Port |
|----------|-----------|-------|----------|------|
| 1 — EarlyDog | `build-website-earlydog` | Playful Bauhaus | Local trades | 8080 |
| 2 — BiA | `build-website-bia` | Editorial serif | Professional services | 8082 |
| 3 — Liveblocks | `build-website-liveblocks` | Modern dark/light SaaS | Tech, startups, IT services | 8083 |
| 4 — LoveSeen | `build-website-loveseen` | Luxury editorial beauty | Salons, photographers, wellness, personal brands | 8085 |
