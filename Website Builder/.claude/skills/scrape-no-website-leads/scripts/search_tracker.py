#!/usr/bin/env python3
"""
Search Coverage Tracker

Persists which (trade × city × source) combinations have been searched,
plus their yield stats (businesses checked, no-website count, yield rate).

The tracker file lives at:
  .claude/skills/scrape-no-website-leads/data/search_coverage.json

Usage (as a module):
    from search_tracker import SearchTracker

    tracker = SearchTracker()

    # Record a completed search
    tracker.record(
        trade="maler", city="zürich", source="local.ch",
        businesses_checked=120, no_website_count=14
    )

    # Pick the best uncovered combination to search next
    combo = tracker.pick_next(source_pref="local.ch")
    # → {"trade": {...}, "city": {...}, "source": "local.ch", "score": 0.82}

    # Get stats
    stats = tracker.get_stats()
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SKILL_DIR / "data"
COVERAGE_FILE = DATA_DIR / "search_coverage.json"
MATRIX_FILE = DATA_DIR / "target_matrix.json"

# A combo with yield below this threshold (and at least one prior attempt) is skipped
LOW_YIELD_THRESHOLD = 0.04  # 4%
# Don't re-search the same combo within this many days
RESCRAPE_COOLDOWN_DAYS = 30


class SearchTracker:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.coverage: list[dict] = self._load_coverage()
        self._matrix: dict | None = None
        self.coverage_file = COVERAGE_FILE  # exposed for external reference

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_coverage(self) -> list[dict]:
        if COVERAGE_FILE.exists():
            try:
                with open(COVERAGE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        with open(COVERAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.coverage, f, indent=2, ensure_ascii=False)

    def load_matrix(self) -> dict:
        if self._matrix is None:
            with open(MATRIX_FILE, "r", encoding="utf-8") as f:
                self._matrix = json.load(f)
        return self._matrix

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        trade: str,
        city: str,
        source: str,
        businesses_checked: int,
        no_website_count: int,
        raw_query: str = None,
    ):
        """
        Record a completed search.

        Args:
            trade: Trade key from target_matrix (e.g. "maler"). May be "" for ad-hoc searches.
            city: City key from target_matrix (e.g. "zürich"). May be "" for ad-hoc searches.
            source: "local.ch" or "google-maps"
            businesses_checked: Total businesses checked (not just no-website ones).
            no_website_count: How many had no website (= leads found).
            raw_query: Original free-form query string (optional, for reference).
        """
        yield_rate = no_website_count / max(1, businesses_checked)
        entry = {
            "trade": trade.lower().strip() if trade else "",
            "city": city.lower().strip() if city else "",
            "source": source,
            "raw_query": raw_query or f"{trade} in {city}",
            "searched_at": datetime.now().isoformat(),
            "businesses_checked": businesses_checked,
            "no_website_count": no_website_count,
            "yield_rate": round(yield_rate, 3),
        }
        self.coverage.append(entry)
        self._save()
        print(f"  [tracker] Recorded: {trade} in {city} via {source} "
              f"→ {no_website_count}/{businesses_checked} leads ({yield_rate:.0%} yield)")

    # ------------------------------------------------------------------
    # Smart Picker
    # ------------------------------------------------------------------

    def pick_next(
        self,
        source_pref: str = None,
        min_yield_threshold: float = LOW_YIELD_THRESHOLD,
        cooldown_days: int = RESCRAPE_COOLDOWN_DAYS,
        exclude: set = None,
    ) -> dict | None:
        """
        Pick the best uncovered (trade × city × source) combination.

        Priority scoring:
          - City population weight (30%) — bigger cities first
          - Avg trade yield from other cities (40%) — high-performing trades first
          - Avg city yield from other trades (30%) — receptive cities first
          - Skip combos recently searched (within cooldown_days)
          - Skip combos with documented near-zero yield

        Returns:
            Dict with keys: trade, city, source, score
            None if all combinations are covered or exhausted.
        """
        matrix = self.load_matrix()
        cutoff = datetime.now() - timedelta(days=cooldown_days)

        # Build set of combos in cooldown
        in_cooldown: set[tuple] = set()
        # Build yield stats by trade and city
        trade_yields: dict[str, list[float]] = defaultdict(list)
        city_yields: dict[str, list[float]] = defaultdict(list)
        # All yields per (trade, city, source) for skip logic
        combo_yields: dict[tuple, list[float]] = defaultdict(list)

        for r in self.coverage:
            t, c, s = r.get("trade", ""), r.get("city", ""), r.get("source", "")
            if not t or not c:
                continue
            searched_at = datetime.fromisoformat(r["searched_at"])
            if searched_at > cutoff:
                in_cooldown.add((t, c, s))
            yr = r.get("yield_rate")
            # Backfilled records have yield_rate=None — exclude from yield scoring
            # (we don't know businesses_checked, so yield would be misleadingly 100%)
            if yr is not None and not r.get("backfilled"):
                trade_yields[t].append(yr)
                city_yields[c].append(yr)
                combo_yields[(t, c, s)].append(yr)

        # Average yield per trade and city (for scoring uncovered combos)
        trade_avg = {t: sum(v) / len(v) for t, v in trade_yields.items()}
        city_avg = {c: sum(v) / len(v) for c, v in city_yields.items()}
        max_pop = max(ci["population"] for ci in matrix["cities"])

        sources = ["local.ch"]
        if source_pref:
            sources = [source_pref]

        best_score = -1.0
        best_combo = None

        for trade in matrix["trades"]:
            tk = trade["key"]
            for city in matrix["cities"]:
                ck = city["key"]
                for source in sources:
                    combo = (tk, ck, source)

                    # Skip if in cooldown
                    if combo in in_cooldown:
                        continue

                    # Skip if reserved by an in-flight parallel slot
                    if exclude and combo in exclude:
                        continue

                    # Skip if prior attempt had near-zero yield
                    prior = combo_yields.get(combo, [])
                    if prior and max(prior) < min_yield_threshold:
                        continue

                    # Score: population (30%) + trade avg yield (40%) + city avg yield (30%)
                    pop_score = city["population"] / max_pop
                    t_score = trade_avg.get(tk, 0.15)  # default 15% if unknown
                    c_score = city_avg.get(ck, 0.15)
                    score = pop_score * 0.3 + t_score * 0.4 + c_score * 0.3

                    if score > best_score:
                        best_score = score
                        best_combo = {
                            "trade": trade,
                            "city": city,
                            "source": source,
                            "score": round(score, 4),
                        }

        return best_combo

    def get_pending(
        self,
        source_pref: str = None,
        top_n: int = 20,
        min_yield_threshold: float = LOW_YIELD_THRESHOLD,
        cooldown_days: int = RESCRAPE_COOLDOWN_DAYS,
    ) -> list[dict]:
        """
        Return the top N uncovered combinations sorted by priority score, descending.
        """
        matrix = self.load_matrix()
        cutoff = datetime.now() - timedelta(days=cooldown_days)

        in_cooldown: set[tuple] = set()
        trade_yields: dict[str, list[float]] = defaultdict(list)
        city_yields: dict[str, list[float]] = defaultdict(list)
        combo_yields: dict[tuple, list[float]] = defaultdict(list)

        for r in self.coverage:
            t, c, s = r.get("trade", ""), r.get("city", ""), r.get("source", "")
            if not t or not c:
                continue
            searched_at = datetime.fromisoformat(r["searched_at"])
            if searched_at > cutoff:
                in_cooldown.add((t, c, s))
            yr = r.get("yield_rate")
            if yr is not None and not r.get("backfilled"):
                trade_yields[t].append(yr)
                city_yields[c].append(yr)
                combo_yields[(t, c, s)].append(yr)

        trade_avg = {t: sum(v) / len(v) for t, v in trade_yields.items()}
        city_avg = {c: sum(v) / len(v) for c, v in city_yields.items()}
        max_pop = max(ci["population"] for ci in matrix["cities"])

        sources = ["local.ch"]
        if source_pref:
            sources = [source_pref]

        candidates = []
        for trade in matrix["trades"]:
            tk = trade["key"]
            for city in matrix["cities"]:
                ck = city["key"]
                for source in sources:
                    combo = (tk, ck, source)
                    if combo in in_cooldown:
                        continue
                    prior = combo_yields.get(combo, [])
                    if prior and max(prior) < min_yield_threshold:
                        continue
                    pop_score = city["population"] / max_pop
                    t_score = trade_avg.get(tk, 0.15)
                    c_score = city_avg.get(ck, 0.15)
                    score = pop_score * 0.3 + t_score * 0.4 + c_score * 0.3
                    candidates.append({
                        "trade": trade,
                        "city": city,
                        "source": source,
                        "score": round(score, 4),
                    })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_n]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """
        Return aggregated stats: total searches, yield by trade, yield by city,
        total leads found, low-yield combos skipped.
        """
        if not self.coverage:
            return {
                "total_searches": 0,
                "total_businesses_checked": 0,
                "total_no_website": 0,
                "overall_yield": 0.0,
                "by_trade": {},
                "by_city": {},
                "by_source": {},
                "recent_searches": [],
            }

        total_checked = sum(r.get("businesses_checked") or 0 for r in self.coverage)
        total_no_website = sum(r.get("no_website_count") or 0 for r in self.coverage)

        by_trade: dict[str, dict] = defaultdict(lambda: {"checked": 0, "leads": 0, "searches": 0})
        by_city: dict[str, dict] = defaultdict(lambda: {"checked": 0, "leads": 0, "searches": 0})
        by_source: dict[str, dict] = defaultdict(lambda: {"checked": 0, "leads": 0, "searches": 0})

        for r in self.coverage:
            t = r.get("trade") or "unknown"
            c = r.get("city") or "unknown"
            s = r.get("source", "unknown")
            checked = r.get("businesses_checked") or 0
            leads_count = r.get("no_website_count") or 0

            by_trade[t]["checked"] += checked
            by_trade[t]["leads"] += leads_count
            by_trade[t]["searches"] += 1

            by_city[c]["checked"] += checked
            by_city[c]["leads"] += leads_count
            by_city[c]["searches"] += 1

            by_source[s]["checked"] += checked
            by_source[s]["leads"] += leads_count
            by_source[s]["searches"] += 1

        # Add yield_rate to each group
        for group in [by_trade, by_city, by_source]:
            for key, v in group.items():
                v["yield_rate"] = round(v["leads"] / max(1, v["checked"]), 3)

        # Recent 5 searches
        recent = sorted(self.coverage, key=lambda r: r.get("searched_at", ""), reverse=True)[:5]
        recent_summary = [
            f"{r.get('trade', '?')} in {r.get('city', '?')} via {r.get('source', '?')} "
            f"→ {r.get('no_website_count') or 0} leads ({(r.get('yield_rate') or 0):.0%}{'*' if r.get('backfilled') else ''})"
            f"  [{r.get('searched_at', '')[:10]}]"
            for r in recent
        ]

        return {
            "total_searches": len(self.coverage),
            "total_businesses_checked": total_checked,
            "total_no_website": total_no_website,
            "overall_yield": round(total_no_website / max(1, total_checked), 3),
            "by_trade": dict(sorted(by_trade.items(), key=lambda x: -x[1]["yield_rate"])),
            "by_city": dict(sorted(by_city.items(), key=lambda x: -x[1]["yield_rate"])),
            "by_source": dict(by_source),
            "recent_searches": recent_summary,
        }


# ------------------------------------------------------------------
# Helpers for auto-tracking from existing pipeline scripts
# ------------------------------------------------------------------

def _parse_trade_city_from_query(query: str) -> tuple[str, str]:
    """
    Try to extract (trade, city) from a free-form search query like "Maler in Zürich".
    Returns ("", "") if parsing fails.
    """
    # Match "X in Y" pattern
    m = re.match(r"^(.+?)\s+in\s+(.+)$", query.strip(), re.IGNORECASE)
    if m:
        trade = m.group(1).strip().lower()
        city = m.group(2).strip().lower()
        return trade, city
    return "", ""


def auto_record_local_ch(query: str, city: str, businesses_checked: int, no_website_count: int):
    """
    Convenience function called from scrape_local_ch.py at the end of a run.
    Normalizes trade/city and records to tracker.
    """
    try:
        tracker = SearchTracker()
        # Try to match trade key to matrix (fuzzy)
        trade_key = _normalize_key(query)
        city_key = _normalize_key(city)
        tracker.record(
            trade=trade_key,
            city=city_key,
            source="local.ch",
            businesses_checked=businesses_checked,
            no_website_count=no_website_count,
            raw_query=f"{query} in {city}",
        )
    except Exception as e:
        print(f"  [tracker] Warning: could not record search — {e}")


def auto_record_google_maps(search_query: str, businesses_checked: int, no_website_count: int):
    """
    Convenience function called from no_website_pipeline.py at the end of a run.
    Parses "Trade in City" pattern from the search query.
    """
    try:
        tracker = SearchTracker()
        trade_raw, city_raw = _parse_trade_city_from_query(search_query)
        tracker.record(
            trade=_normalize_key(trade_raw) if trade_raw else "",
            city=_normalize_key(city_raw) if city_raw else "",
            source="google-maps",
            businesses_checked=businesses_checked,
            no_website_count=no_website_count,
            raw_query=search_query,
        )
    except Exception as e:
        print(f"  [tracker] Warning: could not record search — {e}")


def _normalize_key(s: str) -> str:
    """Lowercase, strip, normalize umlauts for consistent key matching."""
    return (
        s.lower().strip()
        .replace("ü", "ü")   # keep as-is (matrix uses unicode)
        .replace("ä", "ä")
        .replace("ö", "ö")
    )


if __name__ == "__main__":
    # Quick self-test / status dump
    import sys

    tracker = SearchTracker()
    stats = tracker.get_stats()

    print(f"\n{'='*55}")
    print("SEARCH COVERAGE STATS")
    print(f"{'='*55}")
    print(f"Total searches:      {stats['total_searches']}")
    print(f"Businesses checked:  {stats['total_businesses_checked']}")
    print(f"Leads found:         {stats['total_no_website']}")
    print(f"Overall yield:       {stats['overall_yield']:.1%}")

    if stats["recent_searches"]:
        print(f"\nRecent searches:")
        for s in stats["recent_searches"]:
            print(f"  {s}")

    if stats["by_trade"]:
        print(f"\nYield by trade (top 5):")
        for t, v in list(stats["by_trade"].items())[:5]:
            print(f"  {t:20s}  {v['yield_rate']:.0%}  ({v['leads']} leads / {v['searches']} searches)")

    if stats["by_city"]:
        print(f"\nYield by city (top 5):")
        for c, v in list(stats["by_city"].items())[:5]:
            print(f"  {c:20s}  {v['yield_rate']:.0%}  ({v['leads']} leads / {v['searches']} searches)")

    print(f"\nNext recommended combo:")
    best = tracker.pick_next()
    if best:
        print(f"  {best['trade']['label']} in {best['city']['label']} via {best['source']} (score: {best['score']})")
    else:
        print("  All combinations covered!")
