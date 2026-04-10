# auto_emailer.py — Daily Follow-up Automation

This script scans the Google Sheet and automatically sends follow-up emails for
leads that are overdue. It runs every morning via GitHub Actions (see
`.github/workflows/auto-emailer.yml`), and can also be invoked locally for
testing.

## What it does

For every row in the sheet it checks `status` and `email_sent_date` and routes:

| Condition | Action | Sheet update |
|---|---|---|
| `status="email_sent"` and `days_since < 3` | skip | — |
| `status="email_sent"` and `3 ≤ days_since < 7` | flag for phone call | `next_action = "CALL <phone> (Xd seit Email)"`, `next_action_date = today` |
| `status="email_sent"` and `7 ≤ days_since < 14` | send **Day 7 follow-up** email | `status = "followup_sent"`, `next_action = "WAITING_DAY_14"` |
| `status in ("email_sent", "followup_sent")` and `days_since ≥ 14` | send **Day 14 breakup** email | `status = "breakup_sent"` |

Email generation is reused from `.claude/skills/cold-email/scripts/generate_cold_email.py`
(`generate_day7_email` / `generate_day14_email` / `send_email`), so the wording
and SMTP setup stay identical to the existing manual flow.

## Running locally

From the `Website Builder` directory:

```bash
source .venv/bin/activate

# 1. Dry run — shows what would happen, doesn't send or update the sheet
python execution/auto_emailer.py --dry-run

# 2. Single-lead test — process exactly one row
python execution/auto_emailer.py --lead-id abc123def456 --dry-run

# 3. Real run for a single lead
python execution/auto_emailer.py --lead-id abc123def456

# 4. Real full run (identical to what GitHub Actions does)
python execution/auto_emailer.py
```

Exit codes:
- `0` — success (all sends OK, or nothing to do)
- `1` — fatal error (couldn't open sheet, crashed, etc.)
- `2` — partial success (some sends failed after retries)

Structured JSON logs are written to `Website Builder/logs/YYYY-MM-DD.log` and
also mirrored to stdout so GitHub Actions captures them.

## GitHub Actions setup (one-time)

The workflow runs daily at **07:00 UTC** (≈ 08:00–09:00 Zurich time depending
on daylight savings).

### Required repo secrets

Go to: https://github.com/LStheReal/Website-Sidehustle/settings/secrets/actions
and add the following:

| Secret | Where it comes from |
|---|---|
| `GOOGLE_TOKEN_JSON` | Contents of local `token.json` (`cat "Website Builder/token.json"`). Same value that Cloudflare Wrangler uses. |
| `GOOGLE_CREDENTIALS_JSON` | Contents of local `credentials.json` |
| `LEADS_SHEET_ID` | `1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50` |
| `SMTP_HOST` | `mail.infomaniak.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `info@meine-kmu.ch` |
| `SMTP_PASSWORD` | (from `.env`) |
| `SENDER_NAME` | e.g. `Louise Schuele` |
| `SENDER_EMAIL` | `info@meine-kmu.ch` |
| `SENDER_PHONE` | e.g. `+41 79 xxx xx xx` |

### First run (recommended)

1. Add all secrets above.
2. Go to **Actions → Auto Emailer → Run workflow**.
3. Check the **"Dry run"** box and click **Run workflow**.
4. Wait ~1 minute, click the run, and inspect:
   - **Run auto_emailer** step — look for the JSON summary at the bottom.
   - **auto-emailer-logs-...** artifact — download + unzip to see structured logs.
5. If the dry-run summary looks right (correct counts, no errors), re-run
   **without** the dry-run checkbox for the real send.

After that, the daily cron takes over — no manual action needed.

## Rotating the Google OAuth token

If GitHub Actions starts failing with `invalid_grant` / `token expired`:

```bash
cd "Website Builder"
source .venv/bin/activate

# Re-run browser OAuth flow to get a fresh refresh_token
python3 -c "from execution.google_auth import get_credentials; get_credentials()"

# Copy the contents of the updated token.json into the GitHub secret
cat token.json
# → paste into: GitHub → Settings → Secrets → GOOGLE_TOKEN_JSON → Update
```

(This is the same token that Cloudflare uses — after rotating, update it in
Wrangler too: `cat token.json | npx wrangler pages secret put GOOGLE_TOKEN_JSON --project-name meinekmu`.)

## Troubleshooting

**"No recipient email available"** — the lead has neither `owner_email` nor a
parseable address in the `emails` column. Fix the sheet or skip.

**"Missing draft URLs for Day 7 email"** — the Day 7 template references the 4
draft URLs, which need to be populated in columns 35–38. If the drafts
weren't deployed, the follow-up is skipped (not an error).

**"SMTP retry attempt X/3"** (warn) — transient SMTP failure; the script will
retry with 30s / 60s / 120s backoff. If all 3 attempts fail, that specific
lead is logged as failed and the run exits with code 2. Other leads still go
through.

**"Invalid email_sent_date format"** — the sheet has a non-`YYYY-MM-DD` value
in column 32. Fix the cell.

**"COL_EMAIL_SENT_DATE" discrepancy (historical)** — `generate_cold_email.py`
used to write the Day 0 email date to column 26 (which is
`domain_option_2_purchase`, not `email_sent_date`). This has been fixed — it
now writes to column 32. Any leads emailed *before* the fix may have a stale
date in col 26 and nothing in col 32; those will be silently skipped by the
auto-emailer. If there are any such stragglers, update the sheet manually.
