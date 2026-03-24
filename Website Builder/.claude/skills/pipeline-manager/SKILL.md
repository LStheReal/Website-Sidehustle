# Skill: pipeline-manager

## Description
Orchestrator agent that coordinates all pipeline skills, reads lead status from Google Sheets, runs automated steps, and tells you exactly what manual actions are needed. It's a co-pilot — it handles the automation and you handle the human interactions.

## When to Use
- Morning routine: check what needs to be done today
- Processing new or existing leads through the pipeline
- Getting a status overview of all leads
- After a customer responds, to generate next steps
- Batch processing multiple leads at once

## Usage

### Status Report — See what needs to be done
```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/..." \
  --action report
```

### Process All Leads — Run automation for every lead
```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/..." \
  --sender-name "Luise Schule" \
  --sender-phone "+41 79 123 45 67" \
  --sender-email "luise@example.ch" \
  --action process
```

### Process One Lead — Advance a single lead
```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/..." \
  --lead-id "c966e7e2540c" \
  --sender-name "Luise Schule" \
  --sender-phone "+41 79 123 45 67" \
  --sender-email "luise@example.ch" \
  --action process-one
```

### Send Cold Emails — Batch send emails to leads
```bash
source .venv/bin/activate
python3 .claude/skills/pipeline-manager/scripts/pipeline_manager.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/..." \
  --sender-name "Luise Schule" \
  --sender-phone "+41 79 123 45 67" \
  --sender-email "info@meine-kmu.ch" \
  --action send-emails \
  --count 100
```

This will:
1. First use leads with status `website_created` (websites built, email ready)
2. If not enough, auto-process `new` leads (build websites, deploy) to fill the count
3. Send Day 0 cold emails via SMTP
4. Update sheet status to `email_sent` with date

### Parameters
- `--sheet-url` (required) — Google Sheet URL with leads
- `--action` (required) — One of: `report`, `process`, `process-one`, `send-emails`
- `--lead-id` (required for process-one) — Lead ID to process
- `--sender-name` (required for process/process-one/send-emails) — Your name for emails/scripts
- `--sender-phone` (required for process/process-one/send-emails) — Your phone
- `--sender-email` (required for process/process-one/send-emails) — Your email
- `--count` (optional, default 10) — Number of emails to send (for send-emails)

## Pipeline Logic

| Status | Automated Steps | You Do |
|--------|----------------|--------|
| `new` | Build 3 drafts, deploy, generate outreach | Send email or call |
| `website_created` | Generate cold email or call script | Send email or call |
| `email_sent` | Check timing, generate follow-up | Send follow-up or call |
| `responded` | Generate onboarding email, find domains | Send onboarding email |
| `website_creating` | **Run `process-order` skill** — builds site, deploys, sends both emails automatically | Buy domain, connect domain in Cloudflare |
| `sold` / `rejected` | No action | — |

## Output

Prints:
- Pipeline status counts (leads per status)
- Action items for you (what to do manually, in priority order)
- File paths for generated emails/scripts (copy from .tmp/)

Saves action summary to `.tmp/pipeline_report_TIMESTAMP.json`.

## Google Sheet Columns Used

Reads all 34 columns. The pipeline-manager adds 6 tracking columns (29-34):
- `draft_url_1/2/3` — Live URLs of the 3 draft websites
- `chosen_template` — Which template the customer chose (1/2/3)
- `next_action` — What you need to do next
- `next_action_date` — When the next action is due
