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
- `./scripts/smart_scrape.py` — **Coverage-aware auto-picker**: reads target matrix + history, picks best uncovered combo, runs scraper. Use this for systematic lead generation.
- `./scripts/search_tracker.py` — Tracks every search (trade × city × source) with yield stats. Powers smart_scrape's prioritisation.
- `./scripts/no_website_pipeline.py` — Google Maps pipeline: scrape → filter → verify (auto-records to tracker)
- `./scripts/scrape_local_ch.py` — local.ch pipeline: scrape → filter (auto-records to tracker)
- `./scripts/scrape_google_maps.py` — Google Maps scraper via Apify
- `./scripts/filter_no_website.py` — Smart 2-layer website filter (100+ blocked domains)
- `./scripts/verify_no_website.py` — Domain probe verification (catches false positives)
- `./scripts/update_sheet.py` — Google Sheets sync with deduplication + contact quality filter
- `./scripts/clean_leads.py` — Clean existing sheet: remove leads without contact info or with personal website emails

## Data Files
- `./data/target_matrix.json` — Master list of Swiss trades × cities to cover (edit to add new targets)
- `./data/search_coverage.json` — Auto-generated history of every search with yield stats (never edit manually)

## Systematic Scraping (Recommended)

Use `smart_scrape.py` to systematically cover the target matrix with zero manual decision-making.

```bash
source .venv/bin/activate

# Auto-pick the highest-potential uncovered combo and run it
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py next

# Preview what would be picked (no scraping)
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py next --dry-run

# See coverage stats + yield rates by trade and city
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py status

# List top 20 pending combos
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py pending

# Run a specific combo manually
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py run --trade maler --city zürich

# Use Google Maps instead of local.ch
python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py next --source google-maps
```

**How prioritisation works:**
- Picks the highest-scoring uncovered (trade × city × source) combo
- Score = city population (30%) + avg trade yield from other cities (40%) + avg city yield from other trades (30%)
- Skips combos searched in the last 30 days (cooldown)
- Skips combos with a documented yield < 4% (low potential)
- As more searches complete, yield data improves the scoring accuracy

**Target matrix:** `data/target_matrix.json` — 20 trades × 30 cities × 2 sources = 1,200 total combinations.
Add new trades/cities there to expand coverage.

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

### Step 2: Enrich Contacts via Sonnet Agent

After the script completes, spawn a **Sonnet agent** to enrich contacts. This keeps token costs low by avoiding sending the full conversation context.

**How to do it:** Read the output file from Step 1, then spawn ONE agent (model: "sonnet") with all businesses in its prompt. The agent uses WebSearch to find contacts and returns structured JSON.

```
Agent(
    model="sonnet",
    description="Enrich lead contacts",
    prompt="""You are a lead enrichment agent. For each business below, use WebSearch to find contact info.

For each business, run these searches:
1. "{business_name}" {city} Kontakt Email Inhaber
2. "{business_name}" {city} Impressum
3. "{business_name}" {city} Geschäftsführer

Extract from search results:
- owner_name — Owner/manager name
- owner_email — Direct email (MUST be from a real email provider like gmail.com, outlook.com, bluewin.ch, gmx.ch — NOT personal website domains)
- owner_phone — Owner's direct phone
- emails — All provider email addresses found (comma-separated)
- facebook, instagram, linkedin — Social media profile URLs

IMPORTANT EMAIL RULES:
- ONLY accept emails from known email providers (gmail.com, outlook.com, hotmail.com, bluewin.ch, gmx.ch, gmx.net, protonmail.com, yahoo.com, icloud.com, etc.)
- REJECT any email ending with a business/personal website domain (e.g., info@malerei-mueller.ch, hello@spa-beauty.ch) — these businesses have no website so these emails likely don't work
- If no provider email found, leave email fields empty — the phone from Google Maps is still useful

After searching ALL businesses, write the results to a file at: {output_path}

The file must be valid JSON — a list of objects, one per business, with this structure:
[
  {
    "business_name": "...",
    "owner_name": "...",
    "owner_email": "...",
    "owner_phone": "...",
    "emails": ["..."],
    "facebook": "...",
    "instagram": "...",
    "linkedin": "..."
  }
]

Here are the businesses to enrich:
{businesses_json}
"""
)
```

Replace `{businesses_json}` with the JSON array of businesses from Step 1 (include business_name, category, city, state, phone for each).
Replace `{output_path}` with `.tmp/enriched_contacts_TIMESTAMP.json`.

### Step 3: Build Lead Records

After the agent returns, read its output file and merge with the original business data using `flatten_lead()`:

```python
from no_website_pipeline import flatten_lead

lead = flatten_lead(
    gmaps_data=business,           # from pipeline output
    contacts=extracted_contacts,    # from agent's JSON output
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

### Step 5: Build & Deploy Draft Websites

After saving leads to Google Sheets, **immediately** build and deploy all 4 draft websites for every new lead:

```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py --action process
```

This will:
1. Read all leads with status `"new"` from the sheet
2. Build 4 template variants (earlydog, bia, liveblocks, loveseen) for each lead
3. Deploy each to Cloudflare Pages (~15s between deploys to avoid rate limits)
4. Update the sheet: status → `"website_created"`, fills `draft_url_1`–`draft_url_4`
5. Set `next_action` → `"READY TO SEND EMAIL"` (or `"READY TO CALL"` if no email found)

Sender info is read automatically from `SENDER_NAME`/`SENDER_EMAIL` in `.env` — no extra args needed.

**Note:** Requires Wrangler to be authenticated. If the script warns "Wrangler not authenticated", run `npx wrangler login` and re-run.

After this step, report back with the draft URLs and whether each lead is ready to email or call.

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
7. Run pipeline-manager --action process to build & deploy 4 draft websites for each new lead
8. Report: "Found 5 verified no-website businesses, enriched contacts for 4, built drafts for 5. Ready to send email."
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
7. Run pipeline-manager --action process to build & deploy 4 draft websites for each new lead
8. Report results with draft URLs
```

## Pipeline Architecture

```
Source A: Google Maps → Filter (blocklist) → Verify (domain probe) ─┐
                                                                     ├→ Sonnet Agent (WebSearch enrichment) → Contact filter → Sheet
Source B: local.ch → Filter (no website field) ─────────────────────┘
```

**Why a Sonnet agent?** The enrichment step (WebSearch + extraction) is the most token-heavy part. Running it as a separate Sonnet agent avoids sending the full conversation context with every search query, cutting token costs by ~90%. Sonnet is more than capable for this structured extraction task.

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
1. **local.ch Scrape** — Playwright (headless Chromium) visits listing + detail pages directly
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
| **Total (local.ch)** | **Free (Playwright)** |

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
