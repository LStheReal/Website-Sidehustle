# Skill: deploy-website

## Description
Deploy a static website to Cloudflare Pages. Takes a folder of HTML/CSS/JS files and deploys it with a single command. Optionally updates the Google Sheet with the live URL.

## When to Use
- After building a website (static HTML/CSS/JS is ready in a folder)
- User asks to deploy, publish, or put a website live
- Pipeline step after build-website

## Prerequisites

**One-time setup:**
1. Create a free Cloudflare account at https://dash.cloudflare.com/sign-up
2. Run `npx wrangler login` once to authenticate (opens browser)
3. Optionally set `CLOUDFLARE_ACCOUNT_ID` in `.env` (or let the script auto-detect it)

No API tokens needed — `wrangler login` handles OAuth.

## Usage

```bash
source .venv/bin/activate
python3 .claude/skills/deploy-website/scripts/deploy_website.py \
  --site-dir ".tmp/test_bia_website_1" \
  --project-name "swisstextilreinigung"
```

### With Google Sheet update:
```bash
python3 .claude/skills/deploy-website/scripts/deploy_website.py \
  --site-dir ".tmp/test_bia_website_1" \
  --project-name "swisstextilreinigung" \
  --domain "swisstextilreinigung.ch" \
  --sheet-url "https://docs.google.com/spreadsheets/d/SHEET_ID" \
  --lead-id "c966e7e2540c"
```

### Parameters
- `--site-dir` (required) — Path to the folder containing the static site files
- `--project-name` (required) — Cloudflare Pages project name (lowercase, hyphens ok)
- `--domain` (optional) — Custom domain to configure (e.g. `swisstextilreinigung.ch`)
- `--sheet-url` (optional) — Google Sheet URL to update with live URL
- `--lead-id` (optional) — Lead ID for the sheet row to update

### Google Sheets Integration
When `--sheet-url` is provided, the script updates the lead's row:
- `website_url` → the live Cloudflare Pages URL (e.g. `swisstextilreinigung.pages.dev`)
- `status` → `website_created`

## What It Does

1. **Validates** the site directory exists and contains `index.html`
2. **Creates** a Cloudflare Pages project (if it doesn't exist yet)
3. **Deploys** the site via `npx wrangler pages deploy`
4. **Outputs** the live URL (e.g. `https://swisstextilreinigung.pages.dev`)
5. **Updates** Google Sheet if `--sheet-url` is provided
6. **Prints** custom domain DNS instructions if `--domain` is provided

## Custom Domain Setup

After deployment, to connect a custom domain (e.g. `swisstextilreinigung.ch`):
1. The script prints the required DNS records
2. Add a CNAME record at your domain registrar: `swisstextilreinigung.ch → swisstextilreinigung.pages.dev`
3. Cloudflare auto-provisions SSL once DNS propagates

This can also be done via the Cloudflare dashboard under Pages > Project > Custom domains.

## Hosting Details
- **Cost:** $0 (free forever — unlimited bandwidth)
- **CDN:** Cloudflare global edge (300+ cities)
- **SSL:** Free, automatic
- **Limits:** 500 deploys/month, 100 projects, 20,000 files per project

## Dependencies
- `npm` / `npx` (for Wrangler CLI)
- `wrangler` (auto-installed via npx on first run)
- `gspread` + `google-auth` (for sheet updates, already installed)
