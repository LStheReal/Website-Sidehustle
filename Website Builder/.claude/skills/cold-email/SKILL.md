# Skill: cold-email

## Description
Generate a personalized German cold email for a business without a website. The email shows them 3 live website drafts we already built using their Google Maps data. Also generates Day 7 follow-up and Day 14 breakup email variants.

## When to Use
- After building and deploying 3 draft websites for a lead
- User asks to write a cold email, outreach email, or first contact email
- Pipeline step after deploy (drafts are live on Cloudflare)

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/cold-email/scripts/generate_cold_email.py \
  --business-name "Swiss Textilreinigung" \
  --category "Reinigung" \
  --city "Dietikon" \
  --owner-name "Hans Müller" \
  --website-url-1 "https://swisstextilreinigung-bia.pages.dev" \
  --website-url-2 "https://swisstextilreinigung-liveblocks.pages.dev" \
  --website-url-3 "https://swisstextilreinigung-earlydog.pages.dev" \
  --sender-name "Luise Schule" \
  --sender-phone "+41 79 123 45 67" \
  --sender-email "luise@example.ch"
```

### Parameters
- `--business-name` (required) — Name of the business
- `--category` (required) — Business type in German (e.g., "Maler", "Reinigung")
- `--city` (required) — City
- `--owner-name` (optional) — Owner/contact name for personal greeting
- `--website-url-1` (required) — Live URL for template 1 (Klassisch/BiA)
- `--website-url-2` (required) — Live URL for template 2 (Modern/Liveblocks)
- `--website-url-3` (required) — Live URL for template 3 (Frisch/Earlydog)
- `--sender-name` (required) — Your name for signature
- `--sender-phone` (required) — Your phone for signature
- `--sender-email` (required) — Your email for signature
- `--owner-email` (optional) — Recipient email (for sheet update)
- `--sheet-url` (optional) — Google Sheet URL to update status
- `--lead-id` (optional) — Lead ID for sheet row

## Output

Prints 3 email variants to stdout and saves to `.tmp/cold_emails_TIMESTAMP.json`:
1. **Day 0** — Cold intro with 3 website links
2. **Day 7** — Follow-up with different angle
3. **Day 14** — Breakup email

Each email includes: subject line, body text, and recommended send time.

## Email Principles
- German language (Swiss market)
- Under 120 words per email
- No pricing in cold email
- No ask for logo/values/images (that comes after they respond)
- ONE clear CTA per email
- Personal greeting when owner name is known
