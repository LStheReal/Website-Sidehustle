#!/usr/bin/env python3
"""
Smart Scrape — Coverage-Aware Lead Scraper

Reads the target matrix (trades × cities) and search history to auto-pick
the highest-potential uncovered combination, then runs the appropriate scraper.

Commands:
  next     Auto-pick best combo and run it immediately
  status   Show coverage stats and yield rates
  pending  List top uncovered combinations (without running)
  run      Run a specific trade × city combo

Usage:
  python3 smart_scrape.py next [--source local.ch|google-maps] [--limit N] [--dry-run]
  python3 smart_scrape.py status [--top N]
  python3 smart_scrape.py pending [--source S] [--top N]
  python3 smart_scrape.py run --trade maler --city zürich [--source local.ch] [--limit 20]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Make sibling scripts and project root importable
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parents[3]  # .../Website Builder

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from search_tracker import SearchTracker

DEFAULT_LIMIT = 20
DEFAULT_SOURCE = "local.ch"  # Prefer local.ch: cheaper, Swiss-focused, no API needed


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_local_ch_cmd(trade: dict, city: dict, limit: int) -> list[str]:
    """Build the scrape_local_ch.py command for a given trade+city."""
    return [
        sys.executable,
        str(SCRIPT_DIR / "scrape_local_ch.py"),
        "--query", trade["key"],
        "--city", city["local_ch_key"],
        "--limit", str(limit),
    ]


def _build_google_maps_cmd(trade: dict, city: dict, limit: int) -> list[str]:
    """Build the no_website_pipeline.py command for a given trade+city."""
    search_query = f"{trade['gmaps_term']} in {city['label']}"
    return [
        sys.executable,
        str(SCRIPT_DIR / "no_website_pipeline.py"),
        "--search", search_query,
        "--limit", str(limit),
    ]


def _print_combo(combo: dict, rank: int = None):
    prefix = f"{rank:3d}. " if rank is not None else "  → "
    print(f"{prefix}{combo['trade']['label']:20s} in {combo['city']['label']:20s} "
          f"via {combo['source']:12s}  score={combo['score']:.3f}")


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

def cmd_status(args):
    tracker = SearchTracker()
    stats = tracker.get_stats()

    print(f"\n{'='*60}")
    print("SEARCH COVERAGE STATUS")
    print(f"{'='*60}")
    print(f"Total searches completed : {stats['total_searches']}")
    print(f"Total businesses checked : {stats['total_businesses_checked']}")
    print(f"Total leads found        : {stats['total_no_website']}")
    backfilled_count = sum(1 for r in tracker.coverage if r.get("backfilled"))
    real_count = stats["total_searches"] - backfilled_count
    if backfilled_count:
        print(f"Overall yield rate       : N/A ({backfilled_count} backfilled, {real_count} with real yield data)")
    else:
        print(f"Overall yield rate       : {stats['overall_yield']:.1%}")

    # Matrix coverage
    matrix = tracker.load_matrix()
    total_combos = len(matrix["trades"]) * len(matrix["cities"]) * 2  # ×2 sources
    covered = len(set(
        (r.get("trade"), r.get("city"), r.get("source"))
        for r in tracker.coverage
        if r.get("trade") and r.get("city")
    ))
    print(f"Matrix coverage          : {covered}/{total_combos} combinations searched")

    top_n = getattr(args, "top", 5)

    if stats["by_source"]:
        print(f"\nBy source:")
        for s, v in stats["by_source"].items():
            print(f"  {s:15s}  {v['searches']} searches, {v['leads']} leads, {v['yield_rate']:.0%} yield")

    if stats["by_trade"]:
        print(f"\nTop {top_n} trades by yield:")
        for t, v in list(stats["by_trade"].items())[:top_n]:
            bar = "█" * int(v['yield_rate'] * 20)
            print(f"  {t:20s}  {v['yield_rate']:5.0%}  {bar}  ({v['leads']} leads / {v['searches']} searches)")

    if stats["by_city"]:
        print(f"\nTop {top_n} cities by yield:")
        for c, v in list(stats["by_city"].items())[:top_n]:
            bar = "█" * int(v['yield_rate'] * 20)
            print(f"  {c:20s}  {v['yield_rate']:5.0%}  {bar}  ({v['leads']} leads / {v['searches']} searches)")

    if stats["recent_searches"]:
        print(f"\nRecent searches:")
        for s in stats["recent_searches"]:
            print(f"  {s}")

    print(f"\nNext recommended combo:")
    source_pref = getattr(args, "source", None)
    best = tracker.pick_next(source_pref=source_pref)
    if best:
        _print_combo(best)
        print(f"\n  Run it: python3 smart_scrape.py next --source {best['source']}")
    else:
        print("  All combinations covered — well done!")


def cmd_pending(args):
    tracker = SearchTracker()
    top_n = getattr(args, "top", 20)
    source_pref = getattr(args, "source", None)

    pending = tracker.get_pending(source_pref=source_pref, top_n=top_n)

    if not pending:
        print("All combinations are covered (or in cooldown / below yield threshold).")
        return

    source_label = f" [{source_pref}]" if source_pref else " [all sources]"
    print(f"\nTop {len(pending)} pending combinations{source_label}:\n")
    print(f"  {'#':>3}  {'Trade':20s}  {'City':20s}  {'Source':12s}  Score")
    print(f"  {'─'*3}  {'─'*20}  {'─'*20}  {'─'*12}  ─────")
    for i, combo in enumerate(pending, 1):
        _print_combo(combo, rank=i)

    print(f"\n  Run next: python3 smart_scrape.py next")


def cmd_next(args):
    tracker = SearchTracker()
    source_pref = getattr(args, "source", DEFAULT_SOURCE)
    limit = getattr(args, "limit", DEFAULT_LIMIT)
    dry_run = getattr(args, "dry_run", False)

    best = tracker.pick_next(source_pref=source_pref)
    if not best:
        print("All combinations are covered or below yield threshold. Nothing left to scrape.")
        sys.exit(0)

    trade = best["trade"]
    city = best["city"]
    source = best["source"]

    print(f"\n{'='*60}")
    print(f"SMART SCRAPE — AUTO-SELECTED COMBO")
    print(f"{'='*60}")
    print(f"  Trade  : {trade['label']}")
    print(f"  City   : {city['label']}")
    print(f"  Source : {source}")
    print(f"  Score  : {best['score']}")
    print(f"  Limit  : {limit} leads")

    if source == "local.ch":
        cmd = _build_local_ch_cmd(trade, city, limit)
    else:
        cmd = _build_google_maps_cmd(trade, city, limit)

    print(f"\n  Command: {' '.join(cmd)}\n")

    if dry_run:
        print("  [dry-run] Skipping execution.")
        return

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\n  [smart_scrape] Scraper exited with code {result.returncode}.")
        sys.exit(result.returncode)

    print(f"\n  [smart_scrape] Done. Results recorded to tracker automatically.")


def cmd_run(args):
    if not args.trade or not args.city:
        print("Error: --trade and --city are required for 'run' command.")
        sys.exit(1)

    tracker = SearchTracker()
    matrix = tracker.load_matrix()

    # Find trade in matrix
    trade = next((t for t in matrix["trades"] if t["key"] == args.trade.lower()), None)
    if not trade:
        # Try partial match
        trade = next((t for t in matrix["trades"] if args.trade.lower() in t["key"]), None)
    if not trade:
        print(f"Trade '{args.trade}' not found in matrix. Available trades:")
        for t in matrix["trades"]:
            print(f"  {t['key']}")
        sys.exit(1)

    # Find city in matrix
    city_query = args.city.lower()
    city = next((c for c in matrix["cities"] if c["key"] == city_query), None)
    if not city:
        city = next((c for c in matrix["cities"] if city_query in c["key"] or city_query in c["label"].lower()), None)
    if not city:
        print(f"City '{args.city}' not found in matrix. Available cities:")
        for c in matrix["cities"]:
            print(f"  {c['key']} ({c['label']})")
        sys.exit(1)

    source = getattr(args, "source", DEFAULT_SOURCE) or DEFAULT_SOURCE
    limit = getattr(args, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT

    print(f"\n{'='*60}")
    print(f"SMART SCRAPE — MANUAL RUN")
    print(f"{'='*60}")
    print(f"  Trade  : {trade['label']}")
    print(f"  City   : {city['label']}")
    print(f"  Source : {source}")
    print(f"  Limit  : {limit} leads")

    if source == "local.ch":
        cmd = _build_local_ch_cmd(trade, city, limit)
    else:
        cmd = _build_google_maps_cmd(trade, city, limit)

    print(f"\n  Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\n  [smart_scrape] Scraper exited with code {result.returncode}.")
        sys.exit(result.returncode)


# ------------------------------------------------------------------
# Batch command — parallel dispatch to reach a lead target
# ------------------------------------------------------------------

# Chunk size per combo: small enough that if a city/trade is sparse we don't waste time,
# large enough to be efficient. local.ch checks ~10x this many businesses to find leads.
CHUNK_LOCAL_CH = 15
CHUNK_GOOGLE_MAPS = 20

# Max parallel workers per source (Playwright is RAM-heavy; Apify is API-based so lighter)
MAX_PARALLEL_LOCAL_CH = 1
MAX_PARALLEL_GOOGLE_MAPS = 5

# Regex patterns to parse lead count from subprocess stdout
_RE_LOCAL_CH_LEADS = re.compile(r"No-website businesses:\s*(\d+)")
_RE_GMAPS_LEADS = re.compile(r"Verified \(no website\):\s*(\d+)")
_print_lock = threading.Lock()


def _parse_leads_found(stdout: str, source: str) -> int:
    """Extract the number of leads found from scraper stdout."""
    pattern = _RE_LOCAL_CH_LEADS if source == "local.ch" else _RE_GMAPS_LEADS
    m = pattern.search(stdout)
    return int(m.group(1)) if m else 0


def _run_combo(combo: dict, chunk: int) -> dict:
    """
    Run a single scrape combo in a subprocess. Returns a result dict.
    Called from a worker thread.
    """
    trade = combo["trade"]
    city = combo["city"]
    source = combo["source"]

    if source == "local.ch":
        cmd = _build_local_ch_cmd(trade, city, chunk)
    else:
        cmd = _build_google_maps_cmd(trade, city, chunk)

    with _print_lock:
        print(f"  ▶ Starting: {trade['label']} in {city['label']} via {source}", flush=True)

    # Write output to a temp file and run via os.system to avoid subprocess pipe issues
    out_path = tempfile.mktemp(suffix=".log")
    shell_cmd = " ".join(f'"{c}"' if " " in c else c for c in cmd) + f" > {out_path} 2>&1"
    rc = os.system(f'cd "{PROJECT_ROOT}" && {shell_cmd}')
    rc = rc >> 8  # os.system returns exit status in high byte

    # Read output from temp file
    stdout = ""
    try:
        with open(out_path, "r") as f:
            stdout = f.read()
    except FileNotFoundError:
        pass
    finally:
        try:
            os.unlink(out_path)
        except FileNotFoundError:
            pass

    # Exit code 1 from scraper just means "0 leads found" — not a fatal error
    leads_found = _parse_leads_found(stdout, source)
    success = rc == 0 or leads_found == 0

    return {
        "combo": combo,
        "leads_found": leads_found,
        "success": success,
        "stdout": stdout,
        "stderr": "",
        "returncode": rc,
    }


def cmd_batch(args):
    target = args.target
    source = args.source or DEFAULT_SOURCE
    chunk = args.chunk or (CHUNK_LOCAL_CH if source == "local.ch" else CHUNK_GOOGLE_MAPS)
    parallel = args.parallel or (MAX_PARALLEL_LOCAL_CH if source == "local.ch" else MAX_PARALLEL_GOOGLE_MAPS)

    print(f"\n{'='*60}")
    print(f"BATCH SCRAPE — target {target} leads")
    print(f"{'='*60}")
    print(f"  Source   : {source}")
    print(f"  Parallel : {parallel} concurrent searches")
    print(f"  Chunk    : {chunk} leads per combo")
    print(f"  Est. combos needed: ~{-(-target // chunk)} (may vary by yield)")
    print()

    tracker = SearchTracker()
    total_found = 0
    searches_done = 0
    searches_empty = 0
    reserved: set[tuple] = set()  # combos currently running, excluded from picker
    reserved_lock = threading.Lock()

    def pick_combo() -> dict | None:
        with reserved_lock:
            combo = tracker.pick_next(source_pref=source, exclude=reserved)
            if combo:
                key = (combo["trade"]["key"], combo["city"]["key"], combo["source"])
                reserved.add(key)
            return combo

    def release_combo(combo: dict):
        key = (combo["trade"]["key"], combo["city"]["key"], combo["source"])
        with reserved_lock:
            reserved.discard(key)

    # Sequential dispatch loop — run one combo at a time until target reached.
    while total_found < target:
        # Reload coverage from disk so we see records the subprocess wrote
        tracker.coverage = tracker._load_coverage()

        combo = pick_combo()
        if combo is None:
            print("  No more combos available.")
            break

        res = _run_combo(combo, chunk)
        release_combo(combo)

        found = res["leads_found"]
        total_found += found
        searches_done += 1
        if found == 0:
            searches_empty += 1

        trade_label = res["combo"]["trade"]["label"]
        city_label = res["combo"]["city"]["label"]
        status_icon = "✓" if found > 0 else "○"

        print(f"  {status_icon} Done: {trade_label} in {city_label} → "
              f"{found} leads  [total: {total_found}/{target}]", flush=True)
        if res["returncode"] not in (0, 1) and res["stderr"]:
            print(f"    ⚠ Error: {res['stderr'][-200:]}")

    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"  Leads found    : {total_found}")
    print(f"  Searches run   : {searches_done}")
    print(f"  Empty searches : {searches_empty}  (combos with 0 no-website businesses)")
    if total_found < target:
        remaining = target - total_found
        print(f"  ⚠ Fell short by {remaining} leads — run again to continue or expand the target matrix")
    else:
        print(f"  ✓ Target of {target} reached!")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Coverage-aware lead scraper — auto-picks the best uncovered trade × city combo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-pick best combo and run (default: local.ch, 20 leads)
  python3 smart_scrape.py next

  # Auto-pick, prefer Google Maps, fetch 50 leads
  python3 smart_scrape.py next --source google-maps --limit 50

  # Preview what would be picked without running
  python3 smart_scrape.py next --dry-run

  # Show full coverage stats
  python3 smart_scrape.py status

  # List top 30 pending combinations for local.ch
  python3 smart_scrape.py pending --source local.ch --top 30

  # Run a specific combo
  python3 smart_scrape.py run --trade maler --city zürich --source local.ch --limit 25

  # Batch: find 50 new leads automatically (parallel, coverage-aware)
  python3 smart_scrape.py batch --target 50

  # Batch with Google Maps, custom parallelism
  python3 smart_scrape.py batch --target 100 --source google-maps --parallel 5
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- next --
    p_next = subparsers.add_parser("next", help="Auto-pick best combo and run it")
    p_next.add_argument("--source", choices=["local.ch", "google-maps"],
                        default=DEFAULT_SOURCE,
                        help=f"Scraping source (default: {DEFAULT_SOURCE})")
    p_next.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Max leads to fetch (default: {DEFAULT_LIMIT})")
    p_next.add_argument("--dry-run", action="store_true",
                        help="Print selected combo but don't run scraper")

    # -- status --
    p_status = subparsers.add_parser("status", help="Show coverage stats and yield rates")
    p_status.add_argument("--source", choices=["local.ch", "google-maps"],
                          help="Filter recommendations by source")
    p_status.add_argument("--top", type=int, default=5,
                          help="Show top N trades/cities (default: 5)")

    # -- pending --
    p_pending = subparsers.add_parser("pending", help="List top uncovered combinations")
    p_pending.add_argument("--source", choices=["local.ch", "google-maps"],
                           help="Filter by source")
    p_pending.add_argument("--top", type=int, default=20,
                           help="How many to show (default: 20)")

    # -- run --
    p_run = subparsers.add_parser("run", help="Run a specific trade × city combo")
    p_run.add_argument("--trade", required=True, help="Trade key (e.g. maler)")
    p_run.add_argument("--city", required=True, help="City key (e.g. zürich)")
    p_run.add_argument("--source", choices=["local.ch", "google-maps"],
                       default=DEFAULT_SOURCE,
                       help=f"Source (default: {DEFAULT_SOURCE})")
    p_run.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                       help=f"Max leads (default: {DEFAULT_LIMIT})")

    # -- batch --
    p_batch = subparsers.add_parser("batch", help="Auto-run multiple combos in parallel until target is reached")
    p_batch.add_argument("--target", type=int, required=True,
                         help="Total leads to find (e.g. 50)")
    p_batch.add_argument("--source", choices=["local.ch", "google-maps"],
                         default=DEFAULT_SOURCE,
                         help=f"Source (default: {DEFAULT_SOURCE})")
    p_batch.add_argument("--parallel", type=int, default=None,
                         help=f"Concurrent searches (default: {MAX_PARALLEL_LOCAL_CH} for local.ch, {MAX_PARALLEL_GOOGLE_MAPS} for google-maps)")
    p_batch.add_argument("--chunk", type=int, default=None,
                         help=f"Leads per combo (default: {CHUNK_LOCAL_CH} for local.ch, {CHUNK_GOOGLE_MAPS} for google-maps)")

    args = parser.parse_args()

    if args.command == "next":
        cmd_next(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "pending":
        cmd_pending(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "batch":
        cmd_batch(args)


if __name__ == "__main__":
    main()
