# Skill: cold-email

## Description
Generate a personalized German cold email for a business without a website. Day 0 email is HTML with a 2x2 clickable screenshot grid of 4 live website drafts + a claim code box linking to freshnew.ch. Also generates Day 7 follow-up and Day 14 breakup email variants.

## When to Use
- After building and deploying 4 draft websites for a lead
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
  --lead-id "KMU-4827" \
  --website-url-1 "https://swisstextilreinigung-bia.pages.dev" \
  --website-url-2 "https://swisstextilreinigung-liveblocks.pages.dev" \
  --website-url-3 "https://swisstextilreinigung-earlydog.pages.dev" \
  --website-url-4 "https://swisstextilreinigung-loveseen.pages.dev" \
  --sender-name "Louise Schülé & Mael Dubach" \
  --sender-phone "+41 76 605 90 22" \
  --sender-email "info@freshnew.ch" \
  --owner-email "hans@swisstextilreinigung.ch" \
  --send
```

### Parameters
- `--business-name` (required) — Name of the business
- `--category` (required) — Business type in German (e.g., "Maler", "Reinigung")
- `--city` (required) — City
- `--owner-name` (optional) — Owner/contact name for personal greeting
- `--lead-id` (required) — Lead ID used as claim code on freshnew.ch
- `--website-url-1` (required) — Live URL for template 1 (Klassisch/BiA)
- `--website-url-2` (required) — Live URL for template 2 (Modern/Liveblocks)
- `--website-url-3` (required) — Live URL for template 3 (Frisch/Earlydog)
- `--website-url-4` (required) — Live URL for template 4 (Elegant/Loveseen)
- `--screenshot-url-1..4` (optional) — Custom screenshot image URLs; auto-generated via thum.io if omitted
- `--sender-name` (required) — Your name for signature
- `--sender-phone` (required) — Your phone for signature
- `--sender-email` (required) — Your email for signature
- `--owner-email` (optional) — Recipient email address (required if using `--send`)
- `--sheet-url` (optional) — Google Sheet URL to update status after sending
- `--send` (flag) — Actually send the Day 0 email via SMTP; requires SMTP credentials in `.env`

## SMTP Setup (one-time)

Add to your `.env`:
```
SMTP_HOST=smtp.hostinger.com   # or mail.infomaniak.com
SMTP_PORT=465                  # 465 = SSL, 587 = STARTTLS
SMTP_USER=info@freshnew.ch
SMTP_PASSWORD=your_password
```

Find your SMTP details in your email provider's control panel (Hostinger: hPanel → Email → Manage → SMTP settings).

## Output

Prints 3 email variants to stdout and saves to `.tmp/cold_emails_TIMESTAMP.json`:
1. **Day 0** — HTML cold intro with 2x2 screenshot grid + claim code box
2. **Day 7** — Plain text follow-up with links + claim code reminder
3. **Day 14** — Plain text breakup with final claim code nudge

Each email includes: `subject`, `body` (plain text), `body_html` (HTML, Day 0 only).

## Email Principles
- German language (Swiss market), direct "Sie/Ihr" tone — speaks to the owner personally
- No technical language — "Ihre Website" not "ein Entwurf"
- No pricing in cold emails
- ONE clear CTA per email
- Day 0 is HTML; Day 7+14 are plain text
- Screenshots auto-generated via `https://image.thum.io/get/width/280/{url}` if not provided
- Claim code links to `https://freshnew.ch/claim?code={lead_id}`
