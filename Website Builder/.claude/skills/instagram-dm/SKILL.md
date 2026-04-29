# Instagram DM Outreach

Generate ready-to-send German DMs for leads that have an Instagram profile but no email address.

## When to Use

- User says "instagram leads", "IG leads", "give me instagram DMs", "who do I contact on instagram"
- After scraping, when some leads have no email but have an Instagram URL
- As an alternative outreach channel when WhatsApp + email are not available

## How It Works

1. Reads Google Sheet
2. Filters leads with an `instagram` URL and no `owner_email` (IG-only leads)
3. For each lead: prints the Instagram profile link + a personalized German DM (copy-paste ready)
4. If the lead has a draft website (`draft_url_1`), the DM includes the link directly

No API keys needed. Output is printed to terminal — user clicks the Instagram link, then pastes the DM.

## Usage

```bash
source .venv/bin/activate

# Default: IG-only leads (no email), all statuses
python3 .claude/skills/instagram-dm/scripts/instagram_dm.py

# Only leads with draft websites ready (best to send)
python3 .claude/skills/instagram-dm/scripts/instagram_dm.py --status website_created

# Include leads that have BOTH Instagram AND email
python3 .claude/skills/instagram-dm/scripts/instagram_dm.py --all-ig

# JSON output (for pipeline integration)
python3 .claude/skills/instagram-dm/scripts/instagram_dm.py --format json
```

## Output Format

For each lead:
- Business name + city
- Status + whether a draft website is ready
- **Clickable Instagram URL** — open directly in browser/app
- **DM text** — boxed, copy-paste ready in German

## DM Style

- Short, personal, in German ("Sie" form)
- Introduces Louise / freshnew.ch
- If draft URL exists: includes the live link ("Ich habe eine Musterseite erstellt")
- If no draft: softer ask ("Hätten Sie Interesse?")
- Ends with "Liebe Grüsse, Louise"

## Integration with Pipeline Manager

The pipeline manager should flag leads with `instagram` but no `owner_email` as `INSTAGRAM DM` instead of `READY TO CALL`. This skill handles those.

After sending a DM, manually update the lead's status in the Google Sheet to `email_sent` and note the date in `email_sent_date`.
