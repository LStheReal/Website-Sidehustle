#!/usr/bin/env python3
"""
send_first_emails.py — Weekly cron job for Day 0 cold emails.

Scans the Google Sheet for leads with:
  - status == "website_created"
  - at least one email address (owner_email or emails column)
  - at least one draft URL (draft_url_1 .. draft_url_4)

Sends the Day 0 cold intro email (4 website screenshots + claim code) and
updates the sheet: status → "email_sent", email_sent_date → today.

Designed to run in GitHub Actions (see .github/workflows/send-cold-emails.yml)
but can also be invoked locally:

    python "Website Builder/execution/send_first_emails.py" --dry-run
    python "Website Builder/execution/send_first_emails.py" --lead-id abc123
    python "Website Builder/execution/send_first_emails.py"   # real run

Environment:
    LEADS_SHEET_ID        — Google Sheet ID
    GOOGLE_APPLICATION_CREDENTIALS — path to service account JSON
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD  — Infomaniak SMTP
    SENDER_NAME, SENDER_EMAIL, SENDER_PHONE         — From: header
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../Website Builder/execution
ROOT = HERE.parent                              # .../Website Builder
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLD_EMAIL_SCRIPTS = ROOT / ".claude" / "skills" / "cold-email" / "scripts"
if str(COLD_EMAIL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(COLD_EMAIL_SCRIPTS))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import gspread
from gspread.utils import rowcol_to_a1

from execution.google_auth import get_credentials
from execution.retry_utils import retry_with_backoff
from execution.logging_utils import get_logger

from generate_cold_email import (  # type: ignore
    generate_day0_email,
    get_screenshot_url,
    send_email,
)

log = get_logger("send_first_emails")

# Column indices, 1-based — must match pipeline_manager.py COL dict.
COL = {
    "lead_id": 1,
    "business_name": 4,
    "category": 5,
    "city": 6,
    "owner_name": 14,
    "owner_email": 15,
    "owner_phone": 16,
    "emails": 17,
    "status": 21,
    "email_sent_date": 32,
    "draft_url_1": 35,
    "draft_url_2": 36,
    "draft_url_3": 37,
    "draft_url_4": 38,
    "next_action": 40,
    "next_action_date": 41,
}

SENDER_NAME = os.environ.get("SENDER_NAME", "Louise Schülé & Mael Dubach")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "info@freshnew.ch")
SENDER_PHONE = os.environ.get("SENDER_PHONE", "")
FROM_NAME = os.environ.get("FROM_NAME", "freshNew")


# --- Retry wrappers --------------------------------------------------------

@retry_with_backoff(
    max_attempts=3,
    initial_delay=30.0,
    backoff=2.0,
    on_retry=lambda attempt, exc, delay: log.warn(
        "SMTP retry", attempt=attempt, delay=delay, error=repr(exc)
    ),
)
def _send_email_with_retry(**kwargs):
    send_email(**kwargs)


@retry_with_backoff(
    max_attempts=3,
    initial_delay=2.0,
    backoff=2.0,
    on_retry=lambda attempt, exc, delay: log.warn(
        "Sheets batch_update retry", attempt=attempt, delay=delay, error=repr(exc)
    ),
)
def _batch_update_with_retry(worksheet, updates):
    worksheet.batch_update(updates, value_input_option="USER_ENTERED")


# --- Helpers ---------------------------------------------------------------

def _resolve_sheet_id(override: str | None) -> str:
    if override:
        return override
    sid = os.environ.get("LEADS_SHEET_ID", "").strip()
    if sid:
        return sid
    return "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50"


def open_worksheet(sheet_id_override: str | None):
    creds = get_credentials()
    client = gspread.authorize(creds)
    sid = _resolve_sheet_id(sheet_id_override)
    spreadsheet = client.open_by_key(sid)
    return spreadsheet.sheet1


def row_to_lead(row: list[str]) -> dict:
    def get(col_1based: int) -> str:
        idx = col_1based - 1
        return row[idx].strip() if idx < len(row) else ""
    return {key: get(col) for key, col in COL.items()}


def pick_recipient(lead: dict) -> str | None:
    """Prefer owner_email, fall back to first email token in the `emails` column."""
    if lead["owner_email"]:
        return lead["owner_email"]
    raw = lead["emails"]
    if raw:
        tokens = [t.strip() for t in raw.replace(",", " ").split() if "@" in t]
        if tokens:
            return tokens[0]
    return None


def _cell_update(row: int, col_1based: int, value: str) -> dict:
    return {"range": rowcol_to_a1(row, col_1based), "values": [[value]]}


def is_ready(lead: dict) -> bool:
    """True iff this lead is ready to receive the Day 0 cold email."""
    return (
        lead["status"].lower() == "website_created"
        and pick_recipient(lead) is not None
        and any(lead[f"draft_url_{i}"] for i in range(1, 5))
    )


# --- Core send logic -------------------------------------------------------

def send_first_email(
    lead: dict,
    row_idx_1based: int,
    dry_run: bool,
) -> dict:
    lead_id = lead["lead_id"]
    business = lead["business_name"] or "(unknown)"
    recipient = pick_recipient(lead)

    url1 = lead["draft_url_1"]
    url2 = lead["draft_url_2"]
    url3 = lead["draft_url_3"]
    url4 = lead["draft_url_4"] or url3 or url2 or url1

    ss1 = get_screenshot_url(url1)
    ss2 = get_screenshot_url(url2)
    ss3 = get_screenshot_url(url3)
    ss4 = get_screenshot_url(url4)

    email = generate_day0_email(
        business_name=business,
        owner_name=lead["owner_name"] or None,
        url1=url1, url2=url2, url3=url3, url4=url4,
        ss1=ss1, ss2=ss2, ss3=ss3, ss4=ss4,
        lead_id=lead_id,
        sender_name=SENDER_NAME,
        sender_phone=SENDER_PHONE,
        sender_email=SENDER_EMAIL,
    )

    log.info(
        "Would send" if dry_run else "Sending",
        lead_id=lead_id, business=business, to=recipient,
        subject=email["subject"],
    )

    if not dry_run:
        try:
            _send_email_with_retry(
                to_email=recipient,
                subject=email["subject"],
                body_text=email["body"],
                body_html=email["body_html"],
                from_name=FROM_NAME,
                from_email=SENDER_EMAIL,
            )
        except Exception as exc:
            log.error("Send failed after retries",
                      lead_id=lead_id, error=repr(exc))
            return {
                "action": "send_day0_failed",
                "lead_id": lead_id,
                "business": business,
                "to": recipient,
                "error": repr(exc),
            }

    today = datetime.now().strftime("%Y-%m-%d")
    # auto_emailer.py handles Day 7 / Day 14 timing — just mark sent and clear next_action_date
    updates = [
        _cell_update(row_idx_1based, COL["status"], "email_sent"),
        _cell_update(row_idx_1based, COL["email_sent_date"], today),
        _cell_update(row_idx_1based, COL["next_action"], "WAIT_DAY_7"),
    ]

    return {
        "action": "send_day0",
        "lead_id": lead_id,
        "business": business,
        "to": recipient,
        "updates": updates,
    }


# --- Entry point -----------------------------------------------------------

def run(sheet_id: str | None, dry_run: bool, only_lead_id: str | None) -> dict:
    log.info("send_first_emails starting",
             dry_run=dry_run, only_lead_id=only_lead_id, sender=SENDER_EMAIL)

    worksheet = open_worksheet(sheet_id)
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1:
        log.info("Sheet is empty")
        return {"summary": _empty_summary(dry_run), "actions": []}

    rows = all_values[1:]
    all_updates: list[dict] = []
    actions: list[dict] = []

    for i, row in enumerate(rows):
        lead = row_to_lead(row)

        if only_lead_id and lead["lead_id"] != only_lead_id:
            continue

        if not only_lead_id and not is_ready(lead):
            actions.append({"action": "skip", "lead_id": lead["lead_id"],
                            "reason": f"status={lead['status']!r}"})
            continue

        row_idx_1based = i + 2  # +1 header, +1 1-based

        try:
            result = send_first_email(lead, row_idx_1based, dry_run)
        except Exception as exc:
            log.error("send_first_email crashed",
                      lead_id=lead.get("lead_id"), error=repr(exc))
            actions.append({
                "action": "error",
                "lead_id": lead.get("lead_id"),
                "error": repr(exc),
            })
            continue

        actions.append(result)
        if "updates" in result:
            all_updates.extend(result["updates"])

    if all_updates and not dry_run:
        try:
            _batch_update_with_retry(worksheet, all_updates)
            log.info("Sheet updated", cells=len(all_updates))
        except Exception as exc:
            log.error("Sheet batch_update failed", error=repr(exc))
    elif all_updates:
        log.info("Would update sheet (dry run)", cells=len(all_updates))

    summary = {
        "total_rows": len(rows),
        "ready_found": sum(1 for a in actions if a["action"] in ("send_day0", "send_day0_failed")),
        "sent": sum(1 for a in actions if a["action"] == "send_day0"),
        "failed": sum(1 for a in actions if a["action"].endswith("_failed") or a["action"] == "error"),
        "skipped": sum(1 for a in actions if a["action"] == "skip"),
        "dry_run": dry_run,
    }
    log.info("send_first_emails summary", **summary)
    return {"summary": summary, "actions": actions}


def _empty_summary(dry_run: bool) -> dict:
    return {"total_rows": 0, "ready_found": 0, "sent": 0, "failed": 0,
            "skipped": 0, "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(
        description="Weekly Day-0 cold emailer — sends first emails to ready leads"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without sending or writing to the sheet")
    parser.add_argument("--sheet-id", default=None,
                        help="Override LEADS_SHEET_ID from env")
    parser.add_argument("--lead-id", default=None,
                        help="Process only this lead_id (for testing)")
    args = parser.parse_args()

    try:
        result = run(args.sheet_id, args.dry_run, args.lead_id)
    except Exception as exc:
        log.error("send_first_emails crashed",
                  error=repr(exc), traceback=traceback.format_exc())
        sys.exit(1)

    print(json.dumps(result.get("summary", {}), indent=2))

    if result.get("summary", {}).get("failed", 0) > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
