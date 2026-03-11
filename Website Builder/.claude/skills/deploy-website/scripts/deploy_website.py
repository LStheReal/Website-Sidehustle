#!/usr/bin/env python3
"""
Deploy a static website to Cloudflare Pages.

Takes a folder of HTML/CSS/JS files, deploys via Wrangler CLI,
and optionally updates Google Sheets with the live URL.

Prerequisites:
    - npm/npx installed
    - Run `npx wrangler login` once to authenticate
"""

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import gspread
from dotenv import load_dotenv

# Add project root to path for shared utils
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))
from execution.google_auth import get_credentials
from execution.utils import save_intermediate

load_dotenv()


# --- Validation ---

def validate_site_dir(site_dir: str) -> Path:
    """Validate the site directory exists and contains index.html."""
    path = Path(site_dir).resolve()
    if not path.is_dir():
        print(f"Error: Site directory not found: {path}", file=sys.stderr)
        sys.exit(1)
    if not (path / "index.html").exists():
        print(f"Error: No index.html found in {path}", file=sys.stderr)
        sys.exit(1)
    return path


def sanitize_project_name(name: str) -> str:
    """Sanitize project name for Cloudflare Pages (lowercase, alphanumeric + hyphens)."""
    # Handle German umlauts
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        name = name.replace(old, new).replace(old.upper(), new.capitalize())
    # Strip remaining accents
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    if len(name) > 58:  # Cloudflare limit
        name = name[:58].rstrip("-")
    return name


# --- Wrangler CLI helpers ---

def check_wrangler_auth() -> bool:
    """Check if wrangler is authenticated."""
    try:
        result = subprocess.run(
            ["npx", "wrangler", "whoami"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0 and "not authenticated" not in result.stdout.lower():
            # Extract account info
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("⛅") and not line.startswith("-"):
                    print(f"  Authenticated: {line}")
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def create_project(project_name: str) -> bool:
    """Create a Cloudflare Pages project if it doesn't exist."""
    print(f"  Creating project '{project_name}'...")
    result = subprocess.run(
        ["npx", "wrangler", "pages", "project", "create", project_name, "--production-branch", "main"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode == 0:
        print(f"  Project '{project_name}' created.")
        return True
    elif "already exists" in result.stderr.lower() or "already exists" in result.stdout.lower():
        print(f"  Project '{project_name}' already exists.")
        return True
    else:
        # Print the error but don't fail — deploy might still work
        print(f"  Note: {result.stderr.strip() or result.stdout.strip()}")
        return True


def deploy_site(site_dir: Path, project_name: str) -> str | None:
    """Deploy the site to Cloudflare Pages. Returns the live URL or None."""
    print(f"  Deploying {site_dir} to project '{project_name}'...")
    result = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", str(site_dir), "--project-name", project_name],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT),
    )

    output = result.stdout + "\n" + result.stderr

    if result.returncode != 0:
        print(f"Error: Deployment failed.", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None

    # Extract the URL from wrangler output
    # Wrangler prints something like: "✨ Deployment complete! Take a peek over at https://xxx.pages.dev"
    url = None
    for line in output.splitlines():
        # Look for URLs in the output
        match = re.search(r"https://[a-z0-9-]+\.pages\.dev", line, re.IGNORECASE)
        if match:
            url = match.group(0)
        # Also check for the deployment URL pattern
        match2 = re.search(r"https://[a-z0-9-]+\.[a-z0-9-]+\.pages\.dev", line, re.IGNORECASE)
        if match2:
            url = match2.group(0)

    if not url:
        # Fallback: construct the URL from project name
        url = f"https://{project_name}.pages.dev"

    return url


# --- Custom domain instructions ---

def print_domain_instructions(domain: str, project_name: str):
    """Print DNS setup instructions for custom domain."""
    pages_domain = f"{project_name}.pages.dev"
    print(f"\n=== Custom Domain Setup for {domain} ===")
    print(f"  Add this DNS record at your domain registrar:")
    print(f"")
    print(f"  Type:  CNAME")
    print(f"  Name:  @ (or {domain})")
    print(f"  Value: {pages_domain}")
    print(f"")
    print(f"  Or configure via Cloudflare dashboard:")
    print(f"  https://dash.cloudflare.com/ → Pages → {project_name} → Custom domains → Add")
    print(f"")
    print(f"  SSL will be auto-provisioned once DNS propagates (usually 5-30 min).")


# --- Google Sheets integration ---

COL_LEAD_ID = 1
COL_STATUS = 21
COL_WEBSITE_URL = 25


def update_sheet_with_deployment(sheet_url: str, lead_id: str, live_url: str) -> bool:
    """Update the Google Sheet with the live deployment URL."""
    creds = get_credentials()
    client = gspread.authorize(creds)

    if "/d/" in sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    else:
        sheet_id = sheet_url
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1

    # Find the row with this lead_id
    lead_ids = worksheet.col_values(COL_LEAD_ID)
    row_idx = None
    for i, lid in enumerate(lead_ids):
        if lid == lead_id:
            row_idx = i + 1
            break

    if row_idx is None:
        print(f"  Warning: lead_id '{lead_id}' not found in sheet.")
        return False

    from gspread.utils import rowcol_to_a1

    cells = [
        {"range": rowcol_to_a1(row_idx, COL_WEBSITE_URL), "values": [[live_url]]},
        {"range": rowcol_to_a1(row_idx, COL_STATUS), "values": [["website_created"]]},
    ]
    worksheet.batch_update(cells, value_input_option="USER_ENTERED")

    print(f"  Updated Google Sheet row {row_idx}:")
    print(f"    website_url → {live_url}")
    print(f"    status → website_created")
    return True


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Deploy a static website to Cloudflare Pages")
    parser.add_argument("--site-dir", required=True, help="Path to folder with static site files")
    parser.add_argument("--project-name", required=True, help="Cloudflare Pages project name")
    parser.add_argument("--domain", help="Custom domain to configure (e.g. swisstextilreinigung.ch)")
    parser.add_argument("--sheet-url", help="Google Sheet URL to update with live URL")
    parser.add_argument("--lead-id", help="Lead ID for the sheet row to update")
    args = parser.parse_args()

    # Validate
    site_dir = validate_site_dir(args.site_dir)
    project_name = sanitize_project_name(args.project_name)

    print(f"\n=== Deploying to Cloudflare Pages ===")
    print(f"  Site directory: {site_dir}")
    print(f"  Project name:  {project_name}")
    if args.domain:
        print(f"  Custom domain: {args.domain}")

    # Check auth
    print(f"\nChecking Wrangler authentication...")
    if not check_wrangler_auth():
        print("Error: Wrangler is not authenticated.", file=sys.stderr)
        print("Run `npx wrangler login` first to authenticate.", file=sys.stderr)
        sys.exit(1)

    # Create project
    print(f"\nSetting up project...")
    create_project(project_name)

    # Deploy
    print(f"\nDeploying...")
    live_url = deploy_site(site_dir, project_name)

    if not live_url:
        print("Deployment failed.", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Deployed successfully! ===")
    print(f"  Live URL: {live_url}")

    # Custom domain instructions
    if args.domain:
        print_domain_instructions(args.domain, project_name)

    # Save result
    result = {
        "project_name": project_name,
        "live_url": live_url,
        "site_dir": str(site_dir),
        "custom_domain": args.domain,
        "pages_domain": f"{project_name}.pages.dev",
    }
    output_path = save_intermediate(result, "deployment")
    print(f"\n  Result saved to: {output_path}")

    # Update Google Sheet
    if args.sheet_url and args.lead_id:
        print(f"\nUpdating Google Sheet...")
        update_sheet_with_deployment(args.sheet_url, args.lead_id, live_url)

    # Print JSON for piping
    print(f"\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
