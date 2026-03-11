---
name: scrape-no-website-leads
description: Find businesses that have NO real website using Google Maps and/or local.ch, verify with domain probing, enrich contacts via WebSearch, and save to Google Sheets. Use when user asks to find businesses without websites, scrape leads for website building, or generate prospects for web design services.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, WebSearch
---

# No-Website Lead Scraping

## Goal
Find businesses that lack a real website, verify they truly have none, enrich with contact info, and save to Google Sheets for the website building pipeline.

**Two lead sources:**
- **Google Maps** (via Apify) — broad coverage, needs verification
- **local.ch** (via Apify) — Swiss-specific, more reliable no-website signal

**Quality pipeline:** Scrape → Filter (blocklist) → Verify (domain probe) → Enrich (WebSearch) → Google Sheets

## Scripts
- `./scripts/no_website_pipeline.py` — Google Maps pipeline: scrape → filter → verify
- `./scripts/scrape_local_ch.py` — local.ch pipeline: scrape → filter (no verify needed)
- `./scripts/scrape_google_maps.py` — Google Maps scraper via Apify
- `./scripts/filter_no_website.py` — Smart 2-layer website filter (100+ blocked domains)
- `./scripts/verify_no_website.py` — Domain probe verification (catches false positives)
- `./scripts/update_sheet.py` — Google Sheets sync with deduplication

## Process — FOLLOW THESE STEPS EXACTLY

### Step 1: Run the Pipeline Script

**Option A: Google Maps source** (broad, international)
```bash
source .venv/bin/activate
python3 .claude/skills/scrape-no-website-leads/scripts/no_website_pipeline.py \
  --search "SEARCH_QUERY" --limit LIMIT
```

This script handles:
1. Scrapes Google Maps via Apify
2. Filters to businesses without real websites (smart 2-layer filter)
3. Verifies by probing candidate domains (businessname.ch/.com/.swiss)

Output: `.tmp/verified_no_website_TIMESTAMP.json`

**Option B: local.ch source** (Swiss-focused, more reliable)
```bash
source .venv/bin/activate
python3 .claude/skills/scrape-no-website-leads/scripts/scrape_local_ch.py \
  --query "QUERY" --city "CITY" --limit LIMIT
```

Or with a direct URL:
```bash
python3 .claude/skills/scrape-no-website-leads/scripts/scrape_local_ch.py \
  --search-url "https://www.local.ch/de/q/zürich/maler" --limit 50
```

Output: `.tmp/local_ch_no_website_TIMESTAMP.json`

**Which source to use?**
- Swiss businesses → prefer local.ch (explicit website field, no verification needed)
- International or broader searches → use Google Maps
- Maximum coverage → run both sources and deduplicate

### Step 2: Enrich Contacts with WebSearch

After the script completes, use the **WebSearch tool** to find contact info for each business.

For each business in the output file, search:
```
"{business_name}" {city} Kontakt Email Inhaber
```

Extract from search results:
- **owner_name** — Owner/manager name
- **owner_email** — Direct email
- **emails** — All email addresses found
- **facebook**, **instagram**, **linkedin** — Social media URLs

Tips:
- Also try: `"{business_name}" {city} Impressum` (German legal page with contact info)
- Also try: `"{business_name}" {city} Geschäftsführer` (managing director)
- If no email found, note the phone number from Google Maps data (already in the file)

### Step 3: Build Lead Records

After enrichment, use the `flatten_lead()` function from `no_website_pipeline.py` to merge business data + extracted contacts into the 25-column lead schema.

```python
from no_website_pipeline import flatten_lead

lead = flatten_lead(
    gmaps_data=business,           # from pipeline output
    contacts=extracted_contacts,    # from WebSearch enrichment
    search_query="original search query"
)
```

Or build the lead dicts manually following this schema:
- **Metadata**: lead_id, scraped_at, search_query
- **Business Info**: business_name, category, address, city, state, zip_code, phone, google_maps_url, rating, review_count
- **Contact Info**: owner_name, owner_email, owner_phone, emails, facebook, instagram, linkedin
- **Pipeline Status**: status="new", website_url="", email_sent_date="", response_date="", notes=""

### Step 4: Save to Google Sheets

Save the lead records as a JSON file, then run:
```bash
source .venv/bin/activate
python3 .claude/skills/scrape-no-website-leads/scripts/update_sheet.py \
  --input .tmp/leads_final.json
```

To append to an existing sheet:
```bash
python3 .claude/skills/scrape-no-website-leads/scripts/update_sheet.py \
  --input .tmp/leads_final.json \
  --sheet-url "https://docs.google.com/spreadsheets/d/..."
```

To create a named sheet:
```bash
python3 .claude/skills/scrape-no-website-leads/scripts/update_sheet.py \
  --input .tmp/leads_final.json \
  --sheet-name "Maler Zürich Leads"
```

### Full Example Flow
```
User: "Find painters in Zürich without websites"

You do:
1. Run pipeline: python3 .../no_website_pipeline.py --search "Maler in Zürich" --limit 30
   → Gets 30 businesses, filters to 8 without websites, verifies → 5 confirmed no-website
2. Read .tmp/verified_no_website_*.json
3. For each business, WebSearch: "{name}" Zürich Kontakt Email Inhaber
4. Build lead records with flatten_lead()
5. Save to .tmp/leads_final.json
6. Run update_sheet.py to upload to Google Sheets
7. Report: "Found 5 verified no-website businesses, enriched contacts for 4, saved to Google Sheets: [URL]"
```

### Full Example Flow (local.ch)
```
User: "Find hairdressers in Bern without websites"

You do:
1. Run local.ch: python3 .../scrape_local_ch.py --query "coiffeur" --city "bern" --limit 50
   → Gets 50 results, 15 have no website field
2. Read .tmp/local_ch_no_website_*.json
3. For each business, WebSearch: "{name}" Bern Kontakt Email Inhaber
4. Build lead records with flatten_lead()
5. Save to .tmp/leads_final.json
6. Run update_sheet.py to upload to Google Sheets
7. Report results
```

## Pipeline Architecture

```
Source A: Google Maps → Filter (blocklist) → Verify (domain probe) ─┐
                                                                     ├→ WebSearch enrichment → Sheet
Source B: local.ch → Filter (no website field) ─────────────────────┘
```

### Pipeline Steps (Google Maps)
1. **Google Maps Scrape** — Apify `compass/crawler-google-places` returns business listings
2. **Smart Filter** — Two-layer filter identifies businesses without real websites:
   - Layer 1: Domain blocklist (100+ Swiss/European/global directory & social domains)
   - Layer 2: Optional HTTP redirect check (`--deep-check`)
3. **Domain Verification** — Probes candidate domains (businessname.ch/.com/.swiss):
   - Normalizes name (strip AG/GmbH, handle umlauts ü→ue)
   - Generates slug variants (joined, hyphenated, shortened)
   - HTTP HEAD with 5s timeout, follows redirects
   - If redirect lands on blocklisted domain → still counts as no website
4. **WebSearch Enrichment** — Claude Code searches for owner/contact info
5. **Google Sheet Sync** — Appends new leads, deduplicates by lead_id, color-coded headers

### Pipeline Steps (local.ch)
1. **local.ch Scrape** — Apify `azzouzana/local-ch-search-results-scraper-ppr`
2. **Filter** — Businesses with empty website field = no website (very reliable)
3. **WebSearch Enrichment** — Same as above
4. **Google Sheet Sync** — Same as above

## CLI Reference

### Google Maps Pipeline
| Parameter | Required | Description |
|-----------|----------|-------------|
| `--search` | Yes | Search query (e.g., "Maler in Dietikon") |
| `--limit` | No | Max results (default: 20) |
| `--location` | No | Location filter |
| `--workers` | No | Parallel workers for verification (default: 5) |
| `--deep-check` | No | HTTP deep-check for redirect detection |
| `--skip-verify` | No | Skip domain verification (faster, less accurate) |

### local.ch Pipeline
| Parameter | Required | Description |
|-----------|----------|-------------|
| `--search-url` | Either this or query+city | Direct local.ch URL |
| `--query` | With --city | Search term (e.g., "maler") |
| `--city` | With --query | City (e.g., "zürich") |
| `--language` | No | de/fr/it (default: de) |
| `--limit` | No | Max results (default: 50) |

### Domain Verification (standalone)
| Parameter | Required | Description |
|-----------|----------|-------------|
| `--input` | Yes | Input JSON from filter step |
| `--output` | No | Output file (default: auto in .tmp/) |
| `--workers` | No | Parallel workers (default: 5) |

## Output Schema (25 columns)

**Metadata:** lead_id, scraped_at, search_query

**Business Info:** business_name, category, address, city, state, zip_code, phone, google_maps_url, rating, review_count

**Contact Info:** owner_name, owner_email, owner_phone, emails, facebook, instagram, linkedin

**Pipeline Status:** status, website_url, email_sent_date, response_date, notes

Status values: `new` → `website_creating` → `website_created` → `email_sent` → `responded` → `sold` / `rejected`

## Smart Filter — Blocked Domains

The filter catches websites linking to these categories:
- **Swiss directories**: local.ch, search.ch, klara.ch, localsearch.ch, moneyhouse.ch, ...
- **German directories**: gelbeseiten.de, dasoertliche.de, 11880.com, ...
- **European directories**: europages.com, cylex.com, pagesjaunes.fr, paginegialle.it, ...
- **Social media**: facebook.com, instagram.com, linkedin.com, youtube.com, ...
- **Review sites**: google.com, tripadvisor.com, trustpilot.com, ...
- **Marketplaces**: booking.com, tutti.ch, ricardo.ch, ...

To add more domains: edit `DIRECTORY_DOMAINS` in `filter_no_website.py`.

## Cost
| Component | Per Lead |
|-----------|----------|
| Apify Google Maps | ~$0.01-0.02 |
| Apify local.ch | ~$0.004 |
| Domain verification | Free (HTTP HEAD) |
| WebSearch enrichment | Free (built-in) |
| **Total (Google Maps)** | **~$0.01-0.02** |
| **Total (local.ch)** | **~$0.004** |

## Troubleshooting

- **"No businesses found"**: Include location in query (e.g., "Maler in Dietikon" not just "Maler")
- **"All businesses have real websites"**: Try a different industry or smaller town
- **Verification too aggressive**: Use `--skip-verify` to disable domain probing
- **Auth issues**: Delete `token.json` and re-authenticate
- **Duplicates**: Uses lead_id (MD5 of name|address) for deduplication
- **local.ch returns few results**: Try broader search terms or nearby cities
- **Wrong country results**: Google Maps sometimes returns results from Germany (Baden vs Baden CH) — check addresses

## Environment
```
APIFY_API_TOKEN=your_token
GOOGLE_APPLICATION_CREDENTIALS=credentials.json
```
