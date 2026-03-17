# Website Builder — Agent Instructions

## Project Overview

Automated pipeline that finds businesses without websites, builds websites for them, sends cold email outreach, and tracks everything in Google Sheets.

**Target market:** Switzerland & Europe (Swiss/German/French/Italian directories).

**Pipeline stages:**
1. **Scrape** — Find businesses on Google Maps without a real website
2. **Build 3 Drafts** — Create all 3 template versions using Google Maps data
3. **Deploy Drafts** — Deploy all 3 to Cloudflare Pages (free, temporary URLs)
4. **Cold Outreach** — Email/call with 3 live website links
5. **They Choose** — Customer picks their favorite design
6. **Onboarding** — Collect values, logo, images, domain preference
7. **Build Final** — Refine chosen template with their real content
8. **Find Domain** — Find available .ch/.com domains (only after commitment)
9. **Deploy Final** — Deploy on their chosen domain
10. **Payment** — They pay once final site is live

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
- `scrape-no-website-leads` — Find businesses on Google Maps that have no real website, enrich with owner contact info, save to Google Sheets.

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

### Outreach
- `cold-email` — Generate personalized German cold emails (Day 0 intro + Day 7 follow-up + Day 14 breakup) with 3 live website links.
- `call-assistant` — Generate German call cheat sheet with opening script, objection handling, SMS/WhatsApp template. For no-email leads or phone follow-up.
- `write-email` — General-purpose German email for all stages: onboarding, status update, domain confirmation, delivery, invoice, support.

### Orchestration
- `pipeline-manager` — Orchestrator that coordinates all skills. Reads Google Sheet, runs automated steps (build, deploy, generate emails/scripts), tracks lead status, and tells you what manual actions are needed. Commands: `report` (status overview), `process` (batch all leads), `process-one` (single lead).

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
