# Skill: write-email

## Description
General-purpose German email writer for all stages of the customer relationship after initial cold outreach. Generates contextual emails based on the current pipeline stage: onboarding info requests, status updates, domain confirmation, final delivery, invoicing, and support.

## When to Use
- After a lead responds positively and enters onboarding
- Need to request logo, values, images, or domain preference
- Sending a status update on website progress
- Delivering the final website with domain
- Any customer communication that isn't the initial cold email
- User asks to "write an email" for an existing lead

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/write-email/scripts/generate_email.py \
  --business-name "Swiss Textilreinigung" \
  --owner-name "Hans Müller" \
  --city "Dietikon" \
  --stage "onboarding" \
  --sender-name "Luise Schule" \
  --sender-phone "+41 79 123 45 67" \
  --sender-email "luise@example.ch" \
  --context "They chose Design 2 (Modern). Need their logo and values."
```

### Parameters
- `--business-name` (required) — Business name
- `--owner-name` (optional) — Owner/contact name
- `--city` (required) — City
- `--stage` (required) — Pipeline stage, one of:
  - `onboarding` — Request values, logo, images, domain preference
  - `status_update` — Update on website build progress
  - `domain_confirm` — Confirm domain choice before purchase
  - `delivery` — Final website is live, here's the URL
  - `invoice` — Payment request
  - `support` — General support / follow-up
  - `custom` — Free-form, uses --context for content direction
- `--sender-name` (required) — Your name
- `--sender-phone` (required) — Your phone
- `--sender-email` (required) — Your email
- `--context` (optional) — Additional context to shape the email content
- `--website-url` (optional) — Live website URL to include
- `--domain` (optional) — Domain name to reference
- `--price` (optional) — Price to include in invoice emails

## Output
Prints the email (subject + body) and saves to `.tmp/email_TIMESTAMP.json`.
