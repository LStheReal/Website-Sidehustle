# Website Builder — Agent Instructions

## Project Overview

Automated pipeline that finds businesses without websites, builds websites for them, does WhatsApp/phone/email outreach, and tracks everything in Google Sheets.

**Target market:** Switzerland (German-speaking, local.ch directory).

**Pipeline stages:**
1. **Scrape** — Find businesses on local.ch without a real website
2. **Build 4 Drafts** — Create all 4 template versions using scraped data
3. **Deploy Drafts** — Deploy all 4 to Cloudflare Pages (free, temporary URLs)
4. **WhatsApp** — Send WhatsApp with 4 live website links (Day 0, all leads have phone)
5. **Phone Call** — Follow-up call with personalized script (Day 3)
6. **Email Follow-up** — Email with links (Day 7, only for leads with email)
7. **They Choose** — Customer picks their favorite design
8. **Onboarding** — Collect values, logo, images, domain preference
9. **Build Final** — Refine chosen template with their real content
10. **Find Domain** — Find available .ch/.com domains (only after commitment)
11. **Deploy Final** — Deploy on their chosen domain
12. **Payment** — They pay once final site is live

## The Skills Architecture

**Layer 1: Skills (Intent + Execution bundled)**
- Live in `.claude/skills/`
- Each Skill = `SKILL.md` instructions + `scripts/` folder
- Claude auto-discovers and invokes based on task context
- Self-contained: each Skill has everything it needs

**Layer 2: Orchestration (Decision making)**
- This is you. Your job: intelligent routing.
- Read SKILL.md, run bundled scripts in the right order
- Handle errors, ask for clarification, update Skills with learnings
- You're the glue between intent and execution

**Layer 3: Shared Utilities**
- Common scripts in `execution/` (Google auth, helpers)
- Used across multiple Skills when needed

**Why this works:** if you do everything yourself, errors compound. 90% accuracy per step = 59% success over 5 steps. Push complexity into deterministic scripts. You focus on decision-making.

## Available Skills

### Lead Generation
- `scrape-no-website-leads` — Find businesses on local.ch that have no real website, enrich with owner contact info, save to Google Sheets. Uses smart_scrape.py for coverage-aware batch scraping (9 trades x 24 cities). Google Maps source disabled (zero yield).

### Website Building
- `build-website-bia` — Professional editorial template (serif, split-screen, gold accents)
- `build-website-liveblocks` — Modern dark/light template (SaaS-style, gradients)
- `build-website-earlydog` — Playful startup template (Bauhaus, energetic)
- `build-website-loveseen` — Luxury editorial template (beauty, wellness, serif)
- `adapt-website` — **Build Final**: Takes a chosen template + customer input (description, values, logo, images) and rewrites ALL text with AI. Intelligent image placement. Used after customer orders via dashboard (Pipeline Step 7).
- `create-website-template` — Meta-skill: create new templates from reference sites

### Domain & Deployment
- `find-domain` — Find 3 available .ch/.com domains, check via RDAP/WHOIS, update Google Sheet with clickable buy links.
- `deploy-website` — Deploy static sites to Cloudflare Pages (free), update Google Sheet with live URL.
- `process-order` — **Post-order automation**: triggered automatically after "Website jetzt bestellen" is clicked. Builds the final site, deploys to a unique `kmu-<slug>-<id>.pages.dev` subdomain, updates the sheet, sends internal notification to info@meine-kmu.ch (with live URL, domain purchase link, Cloudflare setup link, lead email), and sends customer thank-you email with 48h promise.

### Outreach
- `whatsapp-outreach` — **Primary outreach channel.** Generate personalized German WhatsApp messages with clickable wa.me deep links. All leads have phone numbers. Variants: day0 (first contact), post_call (after phone), followup (Day 7 reminder).
- `call-assistant` — Generate word-for-word German call scripts for beginners. Includes confidence builders, decision tree, objection handling, and clickable wa.me link to send WhatsApp right after the call. Supports 3 contexts: cold, post-email, post-whatsapp.
- `cold-email` — Generate personalized German cold emails (Day 7 follow-up + Day 14 breakup). Used as secondary channel for leads that have email addresses.
- `write-email` — General-purpose German email for all stages: onboarding, status update, domain confirmation, delivery, invoice, support.

### Orchestration
- `pipeline-manager` — Orchestrator that coordinates all skills. Reads Google Sheet, runs automated steps (build, deploy, generate WhatsApp/emails/scripts), tracks lead status, and tells you what manual actions are needed. Commands: `report` (status overview), `process` (batch all leads), `process-one` (single lead), `send-whatsapp` (generate wa.me links for website_created leads), `send-emails` (send cold emails).

## Conversational Interface

You are the project manager. The user should never need to know script names, CLI flags, or lead IDs. They talk naturally, you route to the right skill.

### Intent Routing

| User says | You do |
|---|---|
| "scrape leads for X" / "find businesses" | **Spawn subagent** (see Subagent Tasks below) |
| "overview" / "status" / "what's going on" | Run `quick_status.py --format json`, summarize in 5-8 lines |
| "what should I do next" | Run `quick_status.py --format json`, highlight top 3 priorities |
| "process everything" / "run pipeline" | **Spawn subagent** (see Subagent Tasks below) |
| "build website for [name]" / "process [name]" | **Spawn subagent** (see Subagent Tasks below) |
| "send whatsapp" / "outreach" | Run `pipeline-manager --action send-whatsapp` |
| "send emails" | Run `pipeline-manager --action send-emails` |
| "write email to [name]" | Find lead, infer stage from status, run `write-email` |
| "find domain for [name]" | Run `find-domain` |
| "prepare call for [name]" | Run `call-assistant` (generates word-for-word script + wa.me link) |
| "adapt/customize website for [name]" | **Spawn subagent** (see Subagent Tasks below) |
| "deploy [name]" | Run `deploy-website` |

### Subagent Tasks

Heavy, multi-step operations (scraping, building, processing) run in a **subagent** to keep the main conversation context small. The subagent gets a fresh context, runs all the scripts, and returns only a short summary to the main conversation.

**Always use the `general-purpose` subagent type.**
**Always activate the venv in every bash command:** `source .venv/bin/activate && ...`
**Working directory for all scripts:** `/Users/louiseschule/Documents/Website-Sidehustle/Website Builder`

#### Scrape leads subagent prompt template
```
You are running the local.ch lead generation pipeline in /Users/louiseschule/Documents/Website-Sidehustle/Website Builder.

Task: Scrape ~[LIMIT] no-website businesses using the coverage-aware batch scraper.

Run this command (activate venv first):
  cd "/Users/louiseschule/Documents/Website-Sidehustle/Website Builder" && source .venv/bin/activate && python3 .claude/skills/scrape-no-website-leads/scripts/smart_scrape.py batch --target [LIMIT] --source local.ch 2>&1 | tee /tmp/scrape_batch.log

The batch command automatically:
- Picks the highest-potential uncovered trade × city combos (never duplicates)
- Runs up to 3 combos in parallel
- Stops each combo early if yield is too low (< 1.5% after 40 businesses)
- Continues until [LIMIT] total leads are found

Each combo that finishes, print a clear update line like:
  ✓ Combo done: [trade] in [city] → [N] leads found [total so far: X/[LIMIT]]

When done, report back:
- Total leads added to Google Sheets
- Each combo that ran and how many leads it found
- Any errors
```

#### Process / build website subagent prompt template
```
You are running the pipeline manager in /Users/louiseschule/Documents/Website-Sidehustle/Website Builder.

Task: [SPECIFIC TASK — e.g., "process all new leads" or "build website for lead_id abc123"]

Run (activate venv first):
  cd "Website Builder" && source .venv/bin/activate && python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py --action [ACTION] [--lead-id ID]

Report back: what was processed, draft URLs generated, any errors.
```

#### Adapt website subagent prompt template
```
You are running the adapt-website skill in /Users/louiseschule/Documents/Website-Sidehustle/Website Builder.

Task: Customize the website for [BUSINESS NAME] with the customer's input: [INPUT SUMMARY].

1. Find the lead: source .venv/bin/activate && python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py --find-lead "[BUSINESS NAME]"
2. Run adapt-website with the lead_id and customer input.

Report back: which template was customized, the live URL, any errors.
```

### Behavioral Rules

1. **Don't ask which skill to use** — auto-route from intent. Just confirm what you're about to do for destructive/send actions.
2. **Spawn subagents for heavy tasks** — Scraping, processing, and website building all run in subagents. Never run these directly in the main conversation. This keeps context small and cheap.
3. **Resolve names, not IDs** — When the user says a business name, use `pipeline_manager.py --find-lead "name"` to get the lead_id. Never ask for hex IDs.
4. **Summarize, don't dump** — For status/overview, keep it conversational: how many leads at each stage, top priorities, what to do now. No raw script output.
5. **Prioritize actions** — overdue follow-ups > leads needing emails > new leads to scrape.
6. **Use `--format json`** — Always pass `--format json` to pipeline_manager scripts. Parse the JSON yourself and present a clean summary. This saves tokens.
7. **Use lightweight scripts first** — For status checks, use `quick_status.py` (read-only, fast). Only run full `pipeline_manager.py --action report` if detailed action items are needed.

### Quick Status Script
```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/quick_status.py --format json
```

### Find Lead by Name
```bash
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py --find-lead "Maler Mueller"
```

## Operating Principles

**1. Skills auto-activate**
Claude picks the right Skill based on your request. Each Skill's description tells Claude when to use it.

**2. Scripts are bundled**
Each Skill has its own `scripts/` folder. Run scripts from there:
```bash
python3 .claude/skills/scrape-no-website-leads/scripts/no_website_pipeline.py --search "Maler in Zürich" --limit 20
```

**3. Self-anneal when things break**
- Read error message and stack trace
- Fix the script and test it again
- Update SKILL.md with what you learned
- System is now stronger

**4. Update Skills as you learn**
Skills are living documents. When you discover API constraints, better approaches, or edge cases — update the SKILL.md. But don't create new Skills without asking.

## Self-Annealing Loop

Errors are learning opportunities. When something breaks:
1. Fix the script
2. Test it
3. Update SKILL.md with new flow
4. System is now stronger

## File Organization

**Deliverables vs Intermediates:**
- **Deliverables**: Google Sheets, websites, emails — cloud-based outputs
- **Intermediates**: Temporary files needed during processing

**Directory structure:**
- `.claude/skills/` — Skills (SKILL.md + scripts/)
- `.tmp/` — Intermediate files (never commit)
- `execution/` — Shared utilities (Google auth, helpers)
- `.env` — Environment variables and API keys
- `credentials.json`, `token.json` — Google OAuth credentials

**Key principle:** Local files are only for processing. Deliverables live in cloud services where the user can access them.

## Environment

Requires in `.env`:
```
APIFY_API_TOKEN=your_token          # Google Maps scraping
GOOGLE_APPLICATION_CREDENTIALS=credentials.json
```

**Haiku subagent**: Contact extraction uses a Haiku subagent (via `Task` tool with `model: "haiku"`), so no separate Anthropic API key is needed — it runs through Claude Code itself.

## Setup

```bash
cd "Website Builder"
source .venv/bin/activate    # Always activate venv first
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
# Place Google OAuth credentials.json in project root
```

**Important:** Always run scripts with the venv activated:
```bash
source .venv/bin/activate
python3 .claude/skills/scrape-no-website-leads/scripts/no_website_pipeline.py --search "Maler in Zürich" --limit 20
```

## Summary

You work with Skills that bundle intent (SKILL.md) with execution (scripts/). Read instructions, make decisions, run scripts, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
