#!/usr/bin/env python3
"""
Verify that "no-website" leads truly lack a website by probing candidate domains.

For each business, generates plausible domain names from the business name
(e.g., "Winti Star Coiffeur" → wintistarcoiffeur.ch, winti-star-coiffeur.ch)
and checks if they resolve to a real site via HTTP HEAD.

If a real domain is found (not a directory/blocklist redirect), the business
is removed from the lead list — it actually has a website.

Usage:
    python3 verify_no_website.py --input .tmp/no_website_20260310.json
    python3 verify_no_website.py --input .tmp/no_website_20260310.json --output .tmp/verified.json
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import blocklist helpers from sibling module
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from filter_no_website import _extract_domain, _domain_matches_blocklist

# Add project root for shared utils
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..", "..", "..", "..")
sys.path.insert(0, PROJECT_ROOT)
from execution.utils import save_intermediate

# Swiss legal suffixes to strip from business names
LEGAL_SUFFIXES = [
    "ag", "gmbh", "sarl", "sàrl", "sa", "s.a.", "s.a.r.l.",
    "kg", "ohg", "e.k.", "ug", "gbr", "inc", "llc", "ltd",
    "einzelfirma", "genossenschaft", "verein",
]

# Generic industry terms that should never be used as standalone domain slugs.
# These match generic portals/directories, not specific businesses.
GENERIC_SLUG_WORDS = {
    # Trades / professions (CH)
    "coiffeur", "coiffeuse", "friseur", "friseurin",
    "maler", "malerin", "malermeister", "malergeschaeft",
    "schreiner", "schreinerei", "schreinerin",
    "elektriker", "elektrikerin",
    "sanitaer", "sanitaerin",
    "gaertner", "gaertnerei", "gaertnerin",
    "reinigung", "reiniger", "reinigerin",
    "baecker", "baeckerei",
    "metzger", "metzgerei",
    "buchhalter", "buchhalterinnen",
    "treuhander", "treuhanderin",
    "anwalt", "anwaeltin",
    "arzt", "aerztin",
    "zahnarzt", "zahnaerztin",
    "blumen", "blumenladen",
    "stadtgaertnerei",
    "gipser", "gipsergeschaeft",
    "dachdecker", "dachdeckerei",
    "schlosser", "schlosserei",
    "schuhmacher", "schuhmacherei",
    "fliesenleger", "tapezierer",
    "nagelstudio", "nageldesign",
    "kosmetik", "kosmetikstudio",
    "lashes", "nails", "nailstudio",
    "hairstyling", "hairstyle",
    "fahrschule", "fahrlehrer",
    "musikschule", "musiklehrer", "musikunterricht",
    "klavierlehrer", "klavierunterricht", "gitarrenlehrer",
    "gesangsunterricht", "gesangslehrer",
    "tanzschule", "tanzunterricht",
    "kampfsport", "kampfschule",
    "yoga", "yogastudio",
    "massagepraxis", "masseur", "masseurin",
    "therapie",
    "zahntechniker", "optiker",
    "spengler", "spenglergeschaeft",
    # Common generic first names (often appear in business names)
    "christian", "peter", "hans", "thomas", "daniel", "michael",
    "stefan", "markus", "andreas", "martin", "beat", "reto",
    "marco", "paul", "kurt", "hugo", "walter", "ernst", "fritz",
    "anna", "maria", "barbara", "nicole", "sandra", "andrea",
    # Generic terms
    "express", "pro", "plus", "service", "services", "studio",
    "center", "centre", "shop", "store", "group", "team",
    "gold", "silber", "weiss", "schwarz", "rot", "blau",
    "beauty", "wellness", "fitness",
}

# Umlaut mappings for domain generation
UMLAUT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss", "é": "e", "è": "e", "ê": "e",
    "à": "a", "â": "a", "ô": "o", "î": "i",
    "ç": "c",
}

# TLDs to probe
TLDS = [".ch", ".com", ".swiss"]


def _normalize_name(name: str) -> str:
    """Lowercase, strip legal suffixes, remove special chars."""
    name = name.lower().strip()
    # Replace umlauts
    for umlaut, replacement in UMLAUT_MAP.items():
        name = name.replace(umlaut, replacement)
    # Remove legal suffixes
    for suffix in LEGAL_SUFFIXES:
        pattern = rf'\b{re.escape(suffix)}\.?\s*$'
        name = re.sub(pattern, '', name, flags=re.IGNORECASE).strip()
    # Split on conjunctions BEFORE joining words — don't create "edelweiss" from "Edel & Weiss"
    for noise in [" & ", " und ", " and ", " + ", " / ", " - "]:
        name = name.replace(noise, " ")
    # Strip punctuation except spaces
    name = re.sub(r'[^\w\s]', '', name)
    return name.strip()


def _is_generic(slug: str) -> bool:
    """Return True if this slug is a generic term that shouldn't be used standalone."""
    return slug.lower() in GENERIC_SLUG_WORDS


def _generate_slugs(name: str) -> list[str]:
    """
    Generate domain slug variants from a normalized business name.

    Conservative: avoids generic words to prevent false-positives.
    """
    words = name.split()
    if not words:
        return []

    slugs = set()

    # Full name joined: "wintistarcoiffeur" — include if non-generic
    full_joined = "".join(words)
    if len(full_joined) >= 5 and not _is_generic(full_joined):
        slugs.add(full_joined)

    # Hyphenated full name: "winti-star-coiffeur"
    if len(words) > 1 and not _is_generic(full_joined):
        slugs.add("-".join(words))

    # First two words joined (handles "Firstname Lastname" → "firstnamelastname")
    # Use total combined length ≥ 8 as quality check — even if first word is generic,
    # the combination is usually specific enough ("paulwittwer", "coiffeurjonas")
    if len(words) >= 2:
        two_joined = "".join(words[:2])
        two_hyphen = "-".join(words[:2])
        if len(two_joined) >= 8 and not _is_generic(two_joined):
            slugs.add(two_joined)
            slugs.add(two_hyphen)

    # Just the first word — only if specific enough (≥ 8 chars, non-generic)
    first_word = words[0]
    if len(first_word) >= 8 and not _is_generic(first_word):
        slugs.add(first_word)

    # Last word only — useful for "Schreiner Dollinger" → "dollinger"
    if len(words) >= 2:
        last_word = words[-1]
        if len(last_word) >= 6 and not _is_generic(last_word):
            slugs.add(last_word)

    # Remove any empty or too-short slugs
    return [s for s in slugs if len(s) >= 5]


def _generate_candidate_domains(business_name: str) -> list[str]:
    """Generate all candidate domains for a business."""
    normalized = _normalize_name(business_name)
    slugs = _generate_slugs(normalized)

    domains = []
    for slug in slugs:
        for tld in TLDS:
            domains.append(f"{slug}{tld}")

    return domains


def _probe_domain(domain: str, timeout: float = 5.0) -> dict | None:
    """
    HTTP HEAD a domain to check if it resolves to a real website.

    Returns dict with domain info if it resolves, None otherwise.
    """
    try:
        import httpx
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
        import httpx

    url = f"https://{domain}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    # Slug from the domain (e.g. "kradolfer" from "kradolfer.ch")
    slug = domain.split(".")[0].lower()

    def _is_unrelated_redirect(probed_domain: str, final_domain: str) -> bool:
        """Return True if the redirect leads to an unrelated domain (e.g. ruggieri.ch → spidersoft.ch)."""
        # Normalize both for comparison (strip www.)
        p = probed_domain.lstrip("www.")
        f = final_domain.lstrip("www.")
        if p == f:
            return False  # Same domain (possibly www added) — fine
        # If the slug doesn't appear in the final domain, it's an unrelated redirect
        if slug not in f:
            return True
        return False

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.head(url, headers=headers)
            final_url = str(response.url)
            final_domain = _extract_domain(final_url)

            # If it redirects to a blocklisted domain, it's not a real website
            if _domain_matches_blocklist(final_domain):
                return None

            # If redirected to an unrelated domain, not their website
            if _is_unrelated_redirect(domain, final_domain):
                return None

            # If we get a successful response (2xx/3xx), it's a real site
            if response.status_code < 400:
                return {
                    "domain": domain,
                    "final_url": final_url,
                    "status_code": response.status_code,
                }
    except Exception:
        pass

    # Also try HTTP (some sites don't have HTTPS)
    try:
        url = f"http://{domain}"
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.head(url, headers=headers)
            final_url = str(response.url)
            final_domain = _extract_domain(final_url)

            if _domain_matches_blocklist(final_domain):
                return None

            if _is_unrelated_redirect(domain, final_domain):
                return None

            if response.status_code < 400:
                return {
                    "domain": domain,
                    "final_url": final_url,
                    "status_code": response.status_code,
                }
    except Exception:
        pass

    return None


def verify_single_business(business: dict) -> dict:
    """
    Verify a single business has no website by probing candidate domains.

    Returns dict with:
        - verified: True if business truly has no website
        - found_domain: domain that was found (if any)
        - candidates_checked: number of domains probed
    """
    name = business.get("title", "") or business.get("business_name", "")
    candidates = _generate_candidate_domains(name)

    result = {
        "business_name": name,
        "verified_no_website": True,
        "found_domain": None,
        "found_url": None,
        "candidates_checked": len(candidates),
    }

    for domain in candidates:
        probe = _probe_domain(domain)
        if probe:
            result["verified_no_website"] = False
            result["found_domain"] = probe["domain"]
            result["found_url"] = probe["final_url"]
            break

    return result


def verify_businesses(
    businesses: list[dict],
    max_workers: int = 8,
) -> tuple[list[dict], list[dict], dict]:
    """
    Verify a batch of businesses, removing those that actually have websites.

    Args:
        businesses: List of business dicts (from filter step).
        max_workers: Parallel workers for domain probing.

    Returns:
        Tuple of (verified_no_website, has_website, stats).
    """
    verified_no_website = []
    has_website = []
    total_candidates = 0

    print(f"  Verifying {len(businesses)} businesses (probing candidate domains)...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_biz = {
            executor.submit(verify_single_business, biz): biz
            for biz in businesses
        }

        for future in as_completed(future_to_biz):
            biz = future_to_biz[future]
            name = biz.get("title", "") or biz.get("business_name", "")

            try:
                result = future.result()
                total_candidates += result["candidates_checked"]

                if result["verified_no_website"]:
                    verified_no_website.append(biz)
                    print(f"    ✓ {name} — no website found ({result['candidates_checked']} domains checked)")
                else:
                    biz["_found_website"] = result["found_url"]
                    has_website.append(biz)
                    print(f"    ✗ {name} — FOUND {result['found_domain']} → removed")
            except Exception as e:
                # On error, keep the business (conservative)
                verified_no_website.append(biz)
                print(f"    ? {name} — error during verification, keeping: {e}")

    stats = {
        "total_input": len(businesses),
        "verified_no_website": len(verified_no_website),
        "removed_has_website": len(has_website),
        "total_domains_probed": total_candidates,
        "removal_rate": round(len(has_website) / len(businesses) * 100, 1) if businesses else 0,
    }

    return verified_no_website, has_website, stats


def main():
    parser = argparse.ArgumentParser(
        description="Verify no-website leads by probing candidate domains"
    )
    parser.add_argument("--input", required=True, help="Input JSON file (from filter step)")
    parser.add_argument("--output", default=None, help="Output JSON file (default: auto in .tmp/)")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers (default: 5)")
    parser.add_argument("--json", action="store_true", help="Output as JSON to stdout")

    args = parser.parse_args()

    # Load input
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            businesses = json.load(f)
    except Exception as e:
        print(f"Error loading {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(businesses)} businesses from {args.input}")

    # Verify
    verified, removed, stats = verify_businesses(businesses, max_workers=args.workers)

    # Print summary
    print(f"\n{'='*60}")
    print(f"VERIFICATION RESULTS")
    print(f"{'='*60}")
    print(f"Input businesses:      {stats['total_input']}")
    print(f"Verified no website:   {stats['verified_no_website']}")
    print(f"Removed (has website): {stats['removed_has_website']} ({stats['removal_rate']}%)")
    print(f"Domains probed:        {stats['total_domains_probed']}")

    if removed:
        print(f"\nRemoved businesses:")
        for biz in removed:
            name = biz.get("title", "") or biz.get("business_name", "")
            url = biz.get("_found_website", "unknown")
            print(f"  - {name} → {url}")

    # Save output
    if args.json:
        print(json.dumps(verified, indent=2, ensure_ascii=False))
    else:
        if args.output:
            output_file = args.output
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
        else:
            output_file = save_intermediate(verified, "verified_no_website")
            return verified, removed, stats

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(verified, f, indent=2, ensure_ascii=False)
        print(f"\nVerified results saved to {output_file}")

    return verified, removed, stats


if __name__ == "__main__":
    main()
