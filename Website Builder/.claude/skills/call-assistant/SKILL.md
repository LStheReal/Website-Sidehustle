# Skill: call-assistant

## Description
Generate a German phone call cheat sheet for reaching out to businesses without websites. Includes opening lines, key business facts, objection handling, and links ready to send via SMS/WhatsApp. Used when no email is available (Day 0) or as follow-up after cold email (Day 2-3).

## When to Use
- No email address found for a lead — call is the only channel
- Day 2-3 after cold email with no response
- User asks to prepare for a phone call with a lead
- Before calling any lead to have all info at a glance

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/call-assistant/scripts/generate_call_script.py \
  --business-name "Swiss Textilreinigung" \
  --category "Reinigung" \
  --city "Dietikon" \
  --phone "+41 44 740 13 62" \
  --owner-name "Hans Müller" \
  --website-url-1 "https://swisstextilreinigung-bia.pages.dev" \
  --website-url-2 "https://swisstextilreinigung-liveblocks.pages.dev" \
  --website-url-3 "https://swisstextilreinigung-earlydog.pages.dev" \
  --sender-name "Luise Schule" \
  --email-sent
```

### Parameters
- `--business-name` (required) — Business name
- `--category` (required) — Business type in German
- `--city` (required) — City
- `--phone` (required) — Business phone number to call
- `--owner-name` (optional) — Owner name for personal greeting
- `--website-url-1/2/3` (required) — 3 live draft URLs
- `--sender-name` (required) — Your name
- `--email-sent` (flag) — Set if cold email was already sent (changes the opening)
- `--address` (optional) — Business address
- `--rating` (optional) — Google Maps rating
- `--review-count` (optional) — Number of reviews

## Output

Prints a structured call cheat sheet to the terminal with:
- Quick info card (business facts at a glance)
- Opening script (varies based on --email-sent flag)
- Conversation flow with branches
- Objection handling
- SMS/WhatsApp message template with links
- Close & next steps
