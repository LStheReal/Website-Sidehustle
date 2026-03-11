# Skill: find-domain

## Description
Find available domain names for a business. Generates smart domain candidates from business name/type/city, checks availability via RDAP (.ch) and WHOIS (.com), and returns 3 available suggestions with all business data bundled for downstream skills.

## When to Use
- After scraping leads (business has no website)
- Before building a website (need a domain first)
- User asks to find/check/suggest domain names for a business

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/find-domain/scripts/find_domain.py \
  --business-name "Swiss Textilreinigung" \
  --business-type "Laundry" \
  --city "Dietikon" \
  --extra-data '{"phone":"+41 44 740 13 62","address":"Steinmürlistrasse 38, 8953 Dietikon","lead_id":"c966e7e2540c"}' \
  --sheet-url "https://docs.google.com/spreadsheets/d/SHEET_ID" \
  --lead-id "c966e7e2540c"
```

### Parameters
- `--business-name` (required) — Name of the business
- `--business-type` (required) — Category/type (e.g., "Painter", "Laundry")
- `--city` (optional) — City for location-based domain suggestions
- `--extra-data` (optional) — JSON string with additional business data to pass through
- `--sheet-url` (optional) — Google Sheet URL to update with domain results
- `--lead-id` (optional) — Lead ID to find the row in the sheet (can also be in --extra-data)

### Google Sheets Integration
When `--sheet-url` is provided, the script automatically updates the lead's row:
- `domain_option_1` → first available domain
- `domain_option_2` → second available domain
- `domain_option_3` → third available domain
- `status` → `website_creating`
- `website_url` → left empty (filled later when domain is chosen)

## Output

JSON file saved to `.tmp/domain_suggestions_TIMESTAMP.json` containing:
- `business` — All input business data (pass-through for downstream skills)
- `suggestions` — 3 available domains with TLD, price estimate, and check method
- `all_checked` — Full list of all candidates checked (for transparency)

## Domain Strategy
- **TLDs:** Only `.ch` and `.com` (no .de, no exotic TLDs)
- **Naming:** Prefers longer, descriptive names over abbreviations
- **Umlauts:** Converted to ASCII (ä→ae, ö→oe, ü→ue)
- **Priority:** `.ch` first, then `.com`

## Availability Checking
- `.ch` domains: RDAP via `rdap.nic.ch` (404 = available)
- `.com` domains: `python-whois` library (no record = available)
- Rate limited: 0.5s between RDAP, 1s between WHOIS

## Cost
- Free to run (RDAP and WHOIS are free)
- `.ch` domains cost ~10-15 CHF/year to register
- `.com` domains cost ~10-15 USD/year to register

## Dependencies
- `httpx` (already installed)
- `python-whois` (added to requirements.txt)

## Known Limitations
- WHOIS can occasionally give false positives (domain shows available but is reserved)
- RDAP for .ch is reliable but may rate-limit on bulk checks
- Script checks ~15 candidates, takes ~10-15 seconds total
