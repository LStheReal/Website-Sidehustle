#!/usr/bin/env python3
"""
auto_emailer.py — Daily cron job for follow-up emails.

Scans the Google Sheet for leads with status == "email_sent" and sends:
  - Day 7 follow-up  (if  7 <= days_since < 14)  → status becomes "followup_sent"
  - Day 14 breakup   (if days_since >= 14)       → status becomes "breakup_sent"
  - Day 3+ call flag (if  3 <= days_since < 7)   → writes next_action = "CALL ..."

Reuses email templates and SMTP sender from the existing cold-email skill.

Designed to run in GitHub Actions (see .github/workflows/auto-emailer.yml)
but can also be invoked locally:

    python "Website Builder/execution/auto_emailer.py" --dry-run
    python "Website Builder/execution/auto_emailer.py" --lead-id abc123
    python "Website Builder/execution/auto_emailer.py"   # real run

Environment:
    LEADS_SHEET_ID        — Google Sheet ID (required unless --sheet-id passed)
    GOOGLE_TOKEN_JSON     — OAuth token (or token.json in working dir)
    GOOGLE_CREDENTIALS_JSON — OAuth client config (or credentials.json)
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD  — Infomaniak SMTP
    SENDER_NAME, SENDER_EMAIL, SENDER_PHONE         — From: header (optional)
"""

import argparse
import html as html_lib
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Make `execution.*` and the cold-email script importable regardless of CWD.
HERE = Path(__file__).resolve().parent                       # .../Website Builder/execution
ROOT = HERE.parent                                           # .../Website Builder
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

# Reused from cold-email skill.
from generate_cold_email import (  # type: ignore
    generate_day7_email,
    generate_day14_email,
    send_email,
)

log = get_logger("auto_emailer")

# Column indices, 1-based, matching pipeline_manager.py COL dict.
COL = {
    "lead_id": 1,
    "business_name": 4,
    "category": 5,
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
    "whatsapp_sent_date": 43,
    "whatsapp_status": 44,
}

SENDER_NAME = os.environ.get("SENDER_NAME", "Louise Schuele")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "info@meine-kmu.ch")
SENDER_PHONE = os.environ.get("SENDER_PHONE", "")


# --- SMTP / Sheets with retry wrappers -------------------------------------

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


# --- helpers ---------------------------------------------------------------

def text_to_html(body: str) -> str:
    """Wrap plain-text email body in minimal HTML that preserves line breaks."""
    escaped = html_lib.escape(body)
    return (
        "<html><body>"
        "<pre style=\"font-family: -apple-system, Helvetica, Arial, sans-serif; "
        "font-size: 14px; white-space: pre-wrap; margin: 0;\">"
        f"{escaped}"
        "</pre></body></html>"
    )


def _resolve_sheet_id(sheet_id_override: str | None) -> str:
    """Resolve the sheet ID from CLI override, LEADS_SHEET_ID, or LEADS_SHEET_URL."""
    if sheet_id_override:
        return sheet_id_override
    sid = os.environ.get("LEADS_SHEET_ID", "").strip()
    if sid:
        return sid
    url = os.environ.get("LEADS_SHEET_URL", "").strip()
    if url and "/d/" in url:
        return url.split("/d/")[1].split("/")[0]
    # Hardcoded fallback matching quick_status.py default.
    return "1ewwwPeuwHXvpOGUZfsS2agZRGZBkXJ-MBy4Bs68v-50"


def open_worksheet(sheet_id_override: str | None):
    creds = get_credentials()
    client = gspread.authorize(creds)
    sid = _resolve_sheet_id(sheet_id_override)
    spreadsheet = client.open_by_key(sid)
    return spreadsheet, spreadsheet.sheet1


def row_to_lead(row: list[str]) -> dict:
    def get(col_1based: int) -> str:
        idx = col_1based - 1
        return row[idx].strip() if idx < len(row) else ""
    return {key: get(col) for key, col in COL.items()}


def pick_recipient(lead: dict) -> str | None:
    """Prefer owner_email, fall back to first @-containing token in `emails`."""
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


# --- Decision logic --------------------------------------------------------

def process_lead(lead: dict, row_idx_1based: int, now: datetime, dry_run: bool) -> dict:
    """
    Decide and (optionally) perform the action for a single lead.

    Returns a result dict: {action, ...}. If the action mutated anything,
    it also includes an "updates" list of batch_update cell specs.
    """
    lead_id = lead["lead_id"]
    business = lead["business_name"] or "(unknown)"
    status = lead["status"].lower()
    email_sent_date = lead["email_sent_date"]

    if status not in ("email_sent", "followup_sent", "whatsapp_sent"):
        return {"action": "skip", "lead_id": lead_id, "reason": f"status={status!r}"}

    # For whatsapp_sent leads: use whatsapp_sent_date, route to email follow-up at Day 7
    if status == "whatsapp_sent":
        wa_date_str = lead.get("whatsapp_sent_date", "")
        if not wa_date_str:
            return {"action": "skip", "lead_id": lead_id, "reason": "no whatsapp_sent_date"}
        try:
            wa_sent = datetime.strptime(wa_date_str, "%Y-%m-%d")
        except ValueError:
            return {"action": "skip", "lead_id": lead_id, "reason": "bad wa date"}
        wa_days = (now - wa_sent).days

        recipient = pick_recipient(lead)

        if wa_days >= 14 and recipient:
            return _send_and_update("day14", lead, row_idx_1based, recipient, wa_days, dry_run)
        elif wa_days >= 7 and recipient:
            has_drafts = all(lead.get(f"draft_url_{i}") for i in (1, 2, 3, 4))
            if has_drafts:
                return _send_and_update("day7", lead, row_idx_1based, recipient, wa_days, dry_run)
            else:
                return {"action": "skip", "lead_id": lead_id, "reason": "missing drafts for Day 7"}
        elif wa_days >= 3:
            phone = lead.get("owner_phone") or lead.get("owner_email") or "(no phone)"
            log.info("Call needed (post-WhatsApp)",
                     lead_id=lead_id, business=business, days_since=wa_days)
            updates = [
                _cell_update(row_idx_1based, COL["next_action"],
                             f"ANRUFEN ({wa_days}d seit WhatsApp)"),
                _cell_update(row_idx_1based, COL["next_action_date"],
                             now.strftime("%Y-%m-%d")),
            ]
            return {
                "action": "call_needed",
                "lead_id": lead_id,
                "business": business,
                "days_since": wa_days,
                "updates": updates,
            }
        return {"action": "skip", "lead_id": lead_id, "reason": f"wa_days={wa_days} (<3)"}

    if not email_sent_date:
        return {"action": "skip", "lead_id": lead_id, "reason": "no email_sent_date"}

    try:
        sent = datetime.strptime(email_sent_date, "%Y-%m-%d")
    except ValueError:
        log.warn("Invalid email_sent_date format",
                 lead_id=lead_id, value=email_sent_date)
        return {"action": "skip", "lead_id": lead_id, "reason": "bad date"}

    days_since = (now - sent).days

    # Day 14 breakup — from either "email_sent" or "followup_sent" status
    if days_since >= 14:
        recipient = pick_recipient(lead)
        if not recipient:
            log.warn("No recipient email", lead_id=lead_id, business=business)
            return {"action": "skip", "lead_id": lead_id, "reason": "no email"}
        return _send_and_update("day14", lead, row_idx_1based, recipient, days_since, dry_run)

    # Day 7 follow-up — only from "email_sent", not from "followup_sent"
    if status == "email_sent" and days_since >= 7:
        recipient = pick_recipient(lead)
        if not recipient:
            log.warn("No recipient email", lead_id=lead_id, business=business)
            return {"action": "skip", "lead_id": lead_id, "reason": "no email"}
        # Day 7 follow-up references the 4 draft URLs — skip if we don't have them.
        has_drafts = all(
            lead[f"draft_url_{i}"] for i in (1, 2, 3, 4)
        )
        if not has_drafts:
            log.warn("Missing draft URLs for Day 7 email",
                     lead_id=lead_id, business=business)
            return {"action": "skip", "lead_id": lead_id, "reason": "missing drafts"}
        return _send_and_update("day7", lead, row_idx_1based, recipient, days_since, dry_run)

    # Day 3-6: flag for phone call, no send
    if status == "email_sent" and days_since >= 3:
        phone = lead["owner_phone"] or "(no phone)"
        log.info("Call needed",
                 lead_id=lead_id, business=business,
                 phone=phone, days_since=days_since)
        updates = [
            _cell_update(row_idx_1based, COL["next_action"],
                         f"CALL {phone} ({days_since}d seit Email)"),
            _cell_update(row_idx_1based, COL["next_action_date"],
                         now.strftime("%Y-%m-%d")),
        ]
        return {
            "action": "call_needed",
            "lead_id": lead_id,
            "business": business,
            "days_since": days_since,
            "updates": updates,
        }

    return {
        "action": "skip",
        "lead_id": lead_id,
        "reason": f"days_since={days_since} (<3)",
    }


def _send_and_update(
    variant: str,
    lead: dict,
    row_idx_1based: int,
    recipient: str,
    days_since: int,
    dry_run: bool,
) -> dict:
    """Generate + (maybe) send email, return the action result including updates."""
    lead_id = lead["lead_id"]
    business = lead["business_name"] or "(unknown)"

    if variant == "day7":
        email = generate_day7_email(
            business_name=business,
            category=lead["category"] or "KMU",
            owner_name=lead["owner_name"] or None,
            url1=lead["draft_url_1"],
            url2=lead["draft_url_2"],
            url3=lead["draft_url_3"],
            url4=lead["draft_url_4"],
            lead_id=lead_id,
            sender_name=SENDER_NAME,
            sender_phone=SENDER_PHONE,
            sender_email=SENDER_EMAIL,
        )
        new_status = "followup_sent"
        next_action = "WAITING_DAY_14"
    elif variant == "day14":
        email = generate_day14_email(
            business_name=business,
            owner_name=lead["owner_name"] or None,
            lead_id=lead_id,
            sender_name=SENDER_NAME,
            sender_phone=SENDER_PHONE,
            sender_email=SENDER_EMAIL,
        )
        new_status = "breakup_sent"
        next_action = ""
    else:
        raise ValueError(f"unknown variant: {variant}")

    log.info(
        "Would send" if dry_run else "Sending",
        lead_id=lead_id, business=business,
        variant=variant, to=recipient, days_since=days_since,
        subject=email["subject"],
    )

    if not dry_run:
        try:
            _send_email_with_retry(
                to_email=recipient,
                subject=email["subject"],
                body_text=email["body"],
                body_html=text_to_html(email["body"]),
                from_name=SENDER_NAME,
                from_email=SENDER_EMAIL,
                inline_images=None,
            )
        except Exception as exc:
            log.error("Send failed after retries",
                      lead_id=lead_id, variant=variant, error=repr(exc))
            return {
                "action": f"send_{variant}_failed",
                "lead_id": lead_id,
                "business": business,
                "error": repr(exc),
            }

    updates = [
        _cell_update(row_idx_1based, COL["status"], new_status),
        _cell_update(row_idx_1based, COL["next_action"], next_action),
        _cell_update(row_idx_1based, COL["next_action_date"], ""),
    ]
    return {
        "action": f"send_{variant}",
        "lead_id": lead_id,
        "business": business,
        "to": recipient,
        "days_since": days_since,
        "updates": updates,
    }


# --- Entry point -----------------------------------------------------------

def run(sheet_id: str | None, dry_run: bool, only_lead_id: str | None) -> dict:
    log.info("auto_emailer starting",
             dry_run=dry_run,
             only_lead_id=only_lead_id,
             sender=SENDER_EMAIL)

    spreadsheet, worksheet = open_worksheet(sheet_id)
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1:
        log.info("Sheet is empty")
        return {"summary": _empty_summary(dry_run), "actions": []}

    rows = all_values[1:]
    now = datetime.now()

    all_updates: list[dict] = []
    actions: list[dict] = []

    for i, row in enumerate(rows):
        lead = row_to_lead(row)
        if only_lead_id and lead["lead_id"] != only_lead_id:
            continue
        row_idx_1based = i + 2  # +1 header row, +1 for 1-based indexing

        try:
            result = process_lead(lead, row_idx_1based, now, dry_run)
        except Exception as exc:
            log.error("process_lead crashed",
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

    # Batch-apply sheet updates
    if all_updates and not dry_run:
        try:
            _batch_update_with_retry(worksheet, all_updates)
            log.info("Sheet updated", cells=len(all_updates))
        except Exception as exc:
            log.error("Sheet batch_update failed",
                      error=repr(exc), cells=len(all_updates))
    elif all_updates:
        log.info("Would update sheet (dry run)", cells=len(all_updates))

    summary = {
        "total_rows": len(rows),
        "skipped": sum(1 for a in actions if a["action"] == "skip"),
        "sent_day7": sum(1 for a in actions if a["action"] == "send_day7"),
        "sent_day14": sum(1 for a in actions if a["action"] == "send_day14"),
        "call_needed": sum(1 for a in actions if a["action"] == "call_needed"),
        "failed": sum(
            1 for a in actions
            if a["action"].endswith("_failed") or a["action"] == "error"
        ),
        "dry_run": dry_run,
    }
    log.info("auto_emailer summary", **summary)
    return {"summary": summary, "actions": actions}


def _empty_summary(dry_run: bool) -> dict:
    return {
        "total_rows": 0,
        "skipped": 0,
        "sent_day7": 0,
        "sent_day14": 0,
        "call_needed": 0,
        "failed": 0,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Daily auto-emailer for follow-ups (Day 7 & Day 14)"
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
        log.error("auto_emailer crashed",
                  error=repr(exc),
                  traceback=traceback.format_exc())
        sys.exit(1)

    # Final summary line to stdout — easy to grep in GitHub Actions logs.
    print(json.dumps(result.get("summary", {}), indent=2))

    # Exit non-zero if any sends failed, so the GH Actions run is flagged.
    if result.get("summary", {}).get("failed", 0) > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
