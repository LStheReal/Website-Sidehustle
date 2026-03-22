# Skill: process-order

## Description
Runs automatically after a lead clicks "Website jetzt bestellen" on the dashboard. Deploys the website to a unique Cloudflare Pages subdomain, sends an internal notification email to info@meine-kmu.ch, and sends a confirmation email to the customer.

## When to Use
- Right after the `/api/lead/<id>/order` endpoint receives a successful order submission
- Manually if an order was processed but the post-order steps didn't run (e.g. retry)

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/process-order/scripts/process_order.py --lead-id <12-char-hex>
```

### Parameters
- `--lead-id` (required) — The 12-char hex lead ID (from the order)
- `--dry-run` (optional) — Build and print emails without sending or deploying

## What It Does

> The website is **not rebuilt** here. When the customer clicks "Website jetzt bestellen",
> `server.py` captures the exact HTML shown in the preview (same AI cache + uploaded images)
> and saves it to `.tmp/order_<lead_id>/`. This script deploys that pre-built folder.

1. **Reads lead data** from Google Sheets
2. **Verifies the pre-built site** at `.tmp/order_<lead_id>/index.html` (built by server.py at order time)
3. **Deploys to a unique Cloudflare Pages project** named `kmu-<business-slug>-<6-char-id>` → URL: `kmu-<slug>-<id>.pages.dev`
4. **Updates Google Sheet** with the deployed URL and status `website_created`
5. **Sends internal notification** to `info@meine-kmu.ch` with:
   - Lead ID
   - Live website URL
   - Domain purchase link (Namecheap search for the chosen domain)
   - Cloudflare custom domain setup link
   - Lead's email address
6. **Sends customer confirmation** to the lead's email with:
   - Thank-you message in German
   - The chosen domain name (shown as the future address)
   - "Ihre Website wird innerhalb von 48 Stunden auf {domain} live geschaltet"
   - Same email style as the cold outreach (dark header, meine-kmu brand)

## Email Details

### Internal notification (to info@meine-kmu.ch)
- Subject: `Neue Bestellung — {business_name} ({lead_id})`
- Plain + HTML
- Checklist format with all action links

### Customer confirmation (to lead email)
- Subject: `Ihre Website ist in Bearbeitung — {business_name}`
- HTML only, same style as Day 0 cold email (dark header, meine-kmu brand)
- No payment mention (not yet integrated)
- Shows chosen domain as "Ihre zukünftige Adresse"
- 48-hour delivery promise
- Contact: info@meine-kmu.ch

## Dependencies
- `gspread`, `google-auth` — sheet access
- `smtplib` — SMTP (Infomaniak: mail.infomaniak.com:587)
- `npx wrangler` — Cloudflare Pages deployment
- `anthropic` — AI content generation (via ANTHROPIC_API_KEY in .env)
- `dotenv` — load .env

## Environment Variables (in .env)
```
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=587
SMTP_USER=info@meine-kmu.ch
SMTP_PASSWORD=...
ANTHROPIC_API_KEY=...
LEADS_SHEET_ID=1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50
```
