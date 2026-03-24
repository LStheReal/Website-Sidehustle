#!/usr/bin/env python3
from __future__ import annotations

"""Automatic Pexels image selection for generated websites."""

import os
import re
import json
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_THEME = "local-service"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_CACHE_PATH = Path(__file__).resolve().parents[1] / ".tmp" / "pexels_search_cache.json"

# Ordered rules: first match wins.
THEME_RULES = [
    ("beauty-salon", ("coiffeur", "friseur", "barber", "beauty", "salon", "hairstyle", "nail", "kosmetik")),
    ("wellness-fitness", ("fitness", "wellness", "yoga", "spa", "massage", "physio", "pilates")),
    ("medical", ("arzt", "zahnarzt", "dental", "clinic", "praxis", "medizin", "therapie")),
    ("construction-trade", ("maler", "sanit", "elektr", "gipser", "schreiner", "bau", "renovation", "plumber")),
    ("food-hospitality", ("restaurant", "cafe", "bistro", "hotel", "bar", "bakery", "pizzeria")),
    ("tech-digital", ("it", "software", "digital", "agentur", "agency", "marketing", "web", "saas")),
    ("professional-office", ("anwalt", "kanzlei", "treuhand", "consult", "berater", "finance", "architekt")),
]

THEME_BASE_QUERIES = {
    "beauty-salon": "hair salon hairstylist beauty studio",
    "wellness-fitness": "wellness spa fitness studio",
    "medical": "medical clinic healthcare",
    "construction-trade": "craftsman construction renovation service",
    "food-hospitality": "restaurant cafe hospitality",
    "tech-digital": "technology digital office team",
    "professional-office": "professional office consulting team",
    "local-service": "local business service team",
}

THEME_CORE_QUERIES = {
    "beauty-salon": "hair salon",
    "wellness-fitness": "wellness studio",
    "medical": "medical clinic",
    "construction-trade": "craftsman at work",
    "food-hospitality": "restaurant interior",
    "tech-digital": "tech office",
    "professional-office": "business office",
    "local-service": "small business",
}

TEMPLATE_PALETTE_HINTS = {
    "earlydog": "soft neutral beige warm tones natural light",
    "bia": "editorial luxury neutral tones beige black minimal",
    "liveblocks": "modern clean cool tones blue light",
    "loveseen": "soft blush cream warm luxury beauty editorial",
}

TEMPLATE_COLOR_OPTIONS = {
    "earlydog": ("white", "yellow"),
    "bia": ("white", "yellow"),
    "liveblocks": ("blue", "teal", "white"),
    "loveseen": ("yellow", "pink", "white"),
}

PALETTE_SLOTS = {"hero", "showcase", "about", "cta", "gallery_1", "gallery_2", "gallery_3"}
SERVICE_SCENE_SLOTS = {"service_1", "service_2", "service_3", "feature", "showcase", "contact", "gallery_1", "gallery_3"}
SCENE_TERMS = ("salon", "hairstylist", "hairdresser", "stylist", "client", "interior", "barber")
PORTRAIT_ONLY_TERMS = ("portrait", "model", "fashion", "face", "close up", "closeup")
MAX_QUERIES_PALETTE_SLOT = 2
MAX_QUERIES_SERVICE_SLOT = 3

THEME_SLOT_QUERIES = {
    "beauty-salon": {
        "hero": [
            "editorial beauty portrait long shiny hair studio",
            "luxury beauty model hair side profile soft light",
            "healthy glossy hair beauty portrait beige background",
            "high end hair salon editorial photography",
        ],
        "showcase": [
            "luxury hair salon interior modern minimal",
            "premium beauty salon workspace clean design",
            "aesthetic salon interior natural light",
        ],
        "service_1": [
            "female hairstylist cutting long hair in salon",
            "woman haircut luxury salon modern",
            "beauty salon haircut woman natural light",
        ],
        "service_2": [
            "balayage hair color woman salon natural look",
            "hair coloring treatment glossy long hair salon",
            "beautiful highlights hair salon luxury woman",
        ],
        "service_3": [
            "wavy glossy hair styling beauty woman salon",
            "blow dry styling long hair salon",
            "hair finishing styling luxury beauty portrait",
        ],
        "feature": [
            "hairstylist working with female client in modern salon",
            "salon service process professional aesthetic",
        ],
        "about": [
            "beauty portrait healthy shiny hair studio",
            "professional hairstylist portrait premium salon",
        ],
        "cta": [
            "glossy healthy hair beauty portrait",
            "editorial beauty portrait soft light luxury",
        ],
        "contact": [
            "clean salon reception interior minimal",
            "beauty studio front desk elegant modern",
        ],
        "gallery_1": [
            "luxury hair salon interior details aesthetic",
        ],
        "gallery_2": [
            "healthy shiny hair woman portrait studio",
            "long glossy hair beauty portrait soft light",
        ],
        "gallery_3": [
            "hair salon workstation mirror aesthetic",
            "hairstylist station salon interior modern",
        ],
    }
}

SLOT_HINTS = {
    "hero": "interior professional",
    "showcase": "workspace atmosphere",
    "cta": "team portrait",
    "contact": "reception frontdesk",
    "about": "team portrait",
    "feature": "service in action",
    "gallery_1": "interior style",
    "gallery_2": "close up detail",
    "gallery_3": "salon workstation",
    "service_1": "service in action",
    "service_2": "customer consultation",
    "service_3": "professional work",
}

SLOT_CORE_HINTS = {
    "hero": "interior",
    "showcase": "workspace",
    "cta": "team",
    "contact": "reception",
    "about": "portrait",
    "feature": "service",
    "gallery_1": "interior",
    "gallery_2": "detail",
    "gallery_3": "salon",
    "service_1": "haircut",
    "service_2": "hair color",
    "service_3": "styling",
}

SLOT_SIZES = {
    "hero": (1600, 1000),
    "showcase": (1600, 900),
    "cta": (1200, 1000),
    "contact": (1000, 1300),
    "about": (1200, 900),
    "feature": (1200, 900),
    "gallery_1": (1400, 1000),
    "gallery_2": (1000, 800),
    "gallery_3": (1000, 800),
    "service_1": (1000, 900),
    "service_2": (1000, 900),
    "service_3": (1000, 900),
}

TEMPLATE_SLOT_SIZES = {
    # BiA has split-screen image blocks that look best with portrait assets.
    "bia": {
        "hero": (1200, 1500),
        "showcase": (2200, 1100),
        "cta": (1200, 1500),
        "contact": (1200, 1600),
    },
    # LoveSeen mixes full-width hero with portrait detail imagery.
    "loveseen": {
        "hero": (1920, 1080),
        "about": (1200, 1500),
        "gallery_1": (1600, 900),
        "gallery_2": (1000, 1200),
        "gallery_3": (1000, 1200),
    },
}

NEGATIVE_TERMS = (
    "sign",
    "storefront",
    "street",
    "building",
    "shop sign",
    "neon sign",
    "road",
    "traffic",
    "outside shop",
    "animal",
    "cat",
    "dog",
    "cartoon",
    "old man",
    "barber shop",
    "barbershop",
    "shop window",
    "vintage",
    "retro",
    "workshop",
    "garage",
    "workbench",
    "hardware",
    "wrench",
    "drill",
)

BEAUTY_BONUS_TERMS = (
    "hair",
    "hairstyle",
    "beauty",
    "salon",
    "portrait",
    "model",
    "stylist",
    "makeup",
    "glossy",
    "shiny",
    "studio",
    "editorial",
    "woman",
    "female",
    "luxury",
    "elegant",
    "minimal",
)

BEAUTY_REQUIRED_BY_SLOT = {
    "hero": ("hair", "beauty", "portrait", "model", "editorial"),
    "showcase": ("salon", "interior", "beauty", "studio"),
    "service_1": ("hair", "stylist", "haircut", "woman", "female"),
    "service_2": ("hair", "color", "balayage", "woman", "female"),
    "service_3": ("hair", "styling", "woman", "female", "beauty"),
    "feature": ("hair", "stylist", "salon", "service"),
    "about": ("portrait", "hair", "beauty", "woman", "model"),
    "cta": ("portrait", "beauty", "hair", "woman", "model"),
    "contact": ("salon", "reception", "interior", "studio"),
    "gallery_1": ("salon", "interior", "beauty"),
    "gallery_2": ("hair", "beauty", "woman", "portrait", "shiny"),
    "gallery_3": ("salon", "hair", "hairstylist", "stylist", "interior", "workstation"),
}


def _pexels_api_key() -> str:
    for key in ("PEXELS_API_KEY", "PEXELS_KEY", "PEXELS_TOKEN"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    # Fallback for older env naming; keeps existing setups functional.
    for key in (
        "UNSPLASH_ACCESS_KEY",
        "UNSPLASH_API_KEY",
        "UNSPLASH_CLIENT_ID",
        "UNSPLASH_APP_ID",
    ):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _clean(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9äöüéèàç\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_keyword(haystack: str, keyword: str) -> bool:
    token = (keyword or "").strip().lower()
    if not token:
        return False
    if len(token) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack))
    return token in haystack


def _load_search_cache() -> Dict[str, List[dict]]:
    try:
        if PEXELS_CACHE_PATH.exists():
            return json.loads(PEXELS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_search_cache(cache: Dict[str, List[dict]]) -> None:
    try:
        PEXELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PEXELS_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def infer_theme(data: dict) -> str:
    """Infer an image theme from business data."""
    haystack = _clean(
        " ".join(
            [
                str(data.get("BUSINESS_NAME", "")),
                str(data.get("BUSINESS_CATEGORY", "")),
                str(data.get("CATEGORY", "")),
                str(data.get("category", "")),
                str(data.get("TAGLINE", "")),
                str(data.get("SEARCH_QUERY", "")),
                str(data.get("SERVICE_1_TITLE", "")),
                str(data.get("SERVICE_2_TITLE", "")),
                str(data.get("SERVICE_3_TITLE", "")),
            ]
        )
    )

    for theme, keywords in THEME_RULES:
        if any(_has_keyword(haystack, keyword) for keyword in keywords):
            return theme
    return DEFAULT_THEME


def _slot_size(slot: str, template_name: str = "") -> tuple[int, int]:
    template_key = _clean(template_name)
    template_sizes = TEMPLATE_SLOT_SIZES.get(template_key, {})
    return template_sizes.get(slot, SLOT_SIZES.get(slot, (1200, 900)))


def _orientation_for_slot(slot: str, template_name: str = "") -> str:
    width, height = _slot_size(slot, template_name)
    ratio = width / max(height, 1)
    if ratio >= 1.15:
        return "landscape"
    if ratio <= 0.85:
        return "portrait"
    return "squarish"


def _append_query(url: str, extra: dict) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update(extra)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _pexels_image_url(photo: dict, slot: str, template_name: str = "") -> Optional[str]:
    src = photo.get("src", {})
    raw_url = (
        src.get("original")
        or src.get("large2x")
        or src.get("large")
        or src.get("medium")
        or src.get("small")
    )
    if not raw_url:
        return None
    width, height = _slot_size(slot, template_name)
    return _append_query(
        raw_url,
        {
            "auto": "compress",
            "cs": "tinysrgb",
            "fit": "crop",
            "crop": "entropy",
            "w": str(width),
            "h": str(height),
            "dpr": "2",
        },
    )


def _build_slot_queries(data: dict, theme: str, slot: str) -> List[str]:
    base = THEME_BASE_QUERIES.get(theme, THEME_BASE_QUERIES[DEFAULT_THEME])
    core = THEME_CORE_QUERIES.get(theme, THEME_CORE_QUERIES[DEFAULT_THEME])
    template_name = _clean(str(data.get("TEMPLATE_NAME", "")))
    palette_hint = TEMPLATE_PALETTE_HINTS.get(template_name, "") if slot in PALETTE_SLOTS else ""
    city = _clean(str(data.get("BUSINESS_CITY") or data.get("CITY") or data.get("city") or ""))
    slot_hint = SLOT_HINTS.get(slot, "professional service")
    slot_core = SLOT_CORE_HINTS.get(slot, "service")

    service_context = ""
    if slot == "service_1":
        service_context = _clean(str(data.get("SERVICE_1_TITLE", "")))
    elif slot == "service_2":
        service_context = _clean(str(data.get("SERVICE_2_TITLE", "")))
    elif slot == "service_3":
        service_context = _clean(str(data.get("SERVICE_3_TITLE", "")))

    queries = []

    themed = THEME_SLOT_QUERIES.get(theme, {}).get(slot, [])
    for q in themed:
        queries.append(q)
        if palette_hint:
            queries.append(f"{q} {palette_hint}")
        if city:
            queries.append(f"{q} {city}")
            if palette_hint:
                queries.append(f"{q} {city} {palette_hint}")

    if service_context:
        queries.append(f"{base} {service_context} {slot_hint}")
        queries.append(f"{core} {service_context} {slot_core}")
        if palette_hint:
            queries.append(f"{base} {service_context} {slot_hint} {palette_hint}")
            queries.append(f"{core} {service_context} {slot_core} {palette_hint}")

    queries.append(f"{base} {slot_hint}")
    queries.append(f"{core} {slot_hint}")
    queries.append(f"{core} {slot_core}")
    queries.append(core)
    if palette_hint:
        queries.append(f"{base} {slot_hint} {palette_hint}")
        queries.append(f"{core} {slot_core} {palette_hint}")
        queries.append(f"{core} {palette_hint}")
    if city:
        queries.append(f"{base} {slot_hint} {city}")
        queries.append(f"{core} {slot_core} {city}")
        if palette_hint:
            queries.append(f"{base} {slot_hint} {city} {palette_hint}")
            queries.append(f"{core} {slot_core} {city} {palette_hint}")

    # Deduplicate while preserving order.
    deduped: List[str] = []
    seen = set()
    for q in queries:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


def _photo_text(photo: dict) -> str:
    text = " ".join(
        [
            str(photo.get("alt", "")),
            str(photo.get("photographer", "")),
            str(photo.get("url", "")),
        ]
    )
    return _clean(text)


def _ratio_delta(photo: dict, slot: str, template_name: str = "") -> float:
    target_w, target_h = _slot_size(slot, template_name)
    target_ratio = target_w / target_h
    width = float(photo.get("width") or target_w)
    height = float(photo.get("height") or target_h)
    ratio = width / max(height, 1.0)
    return abs(ratio - target_ratio)


def _photo_score(photo: dict, slot: str, theme: str, template_name: str = "") -> float:
    text = _photo_text(photo)
    likes_raw = photo.get("likes")
    likes = float(likes_raw or 0)

    ratio_delta = _ratio_delta(photo, slot, template_name)
    ratio_score = max(0.0, 40.0 - (ratio_delta * 80.0))

    score = (likes * 0.2) + ratio_score

    if likes_raw is not None and likes < 10:
        score -= 8.0

    bonus_words = ()
    if theme == "beauty-salon":
        bonus_words = BEAUTY_BONUS_TERMS

    for word in bonus_words:
        if word in text:
            score += 10.0
    for word in NEGATIVE_TERMS:
        if word in text:
            score -= 24.0

    if theme == "beauty-salon":
        required = BEAUTY_REQUIRED_BY_SLOT.get(slot, ("hair", "beauty", "salon"))
        has_required = any(token in text for token in required)
        if has_required:
            score += 18.0
        elif text:
            score -= 18.0

        # For service-like slots we prefer actual salon scenes over pure portraits.
        if slot in SERVICE_SCENE_SLOTS:
            has_scene = any(token in text for token in SCENE_TERMS)
            if has_scene:
                score += 14.0
            elif text:
                score -= 24.0

            if any(token in text for token in PORTRAIT_ONLY_TERMS) and not has_scene:
                score -= 12.0

    return score


def _search_pexels(
    access_key: str,
    query: str,
    orientation: str,
    color: Optional[str] = None,
    per_page: int = 20,
) -> List[dict]:
    cache_key = f"{orientation}|{color or 'any'}|{_clean(query)}|{per_page}"
    cache = _load_search_cache()
    if cache_key in cache:
        return cache[cache_key]

    try:
        import httpx
    except Exception:
        return []

    headers = {"Authorization": access_key}
    provider_orientation = orientation
    if orientation == "squarish":
        provider_orientation = "square"

    params = {
        "query": query,
        "per_page": str(per_page),
        "page": "1",
        "orientation": provider_orientation,
    }
    if color:
        params["color"] = color
    try:
        resp = httpx.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=15.0,
        )
        if resp.status_code != 200:
            if resp.status_code in {403, 429} and cache_key in cache:
                return cache[cache_key]
            return []
        payload = resp.json()
        results = payload.get("photos", []) or []
        cache[cache_key] = results
        _save_search_cache(cache)
        return results
    except Exception:
        return []


def suggest_business_images(data: dict, slot_map: Dict[str, str]) -> Dict[str, str]:
    """Return {placeholder_name: image_url} for requested placeholders via Pexels."""
    access_key = _pexels_api_key()
    if not access_key:
        return {}

    theme = infer_theme(data)
    template_name = _clean(str(data.get("TEMPLATE_NAME", "")))
    search_colors = list(TEMPLATE_COLOR_OPTIONS.get(template_name, ())) + [None]
    used_photo_ids = set()
    query_cache: Dict[str, List[dict]] = {}
    suggestions: Dict[str, str] = {}

    def pick_from_results(
        results: List[dict],
        slot: str,
        allow_used: bool = False,
        min_score: float = 0.0,
        max_ratio_delta: Optional[float] = None,
    ) -> Optional[dict]:
        ranked = sorted(
            results,
            key=lambda p: _photo_score(p, slot, theme, template_name=template_name),
            reverse=True,
        )
        for photo in ranked:
            photo_id = photo.get("id")
            if not photo_id:
                continue
            ratio_delta = _ratio_delta(photo, slot, template_name=template_name)
            if max_ratio_delta is not None and ratio_delta > max_ratio_delta:
                continue
            score = _photo_score(photo, slot, theme, template_name=template_name)
            if score < min_score:
                continue
            if allow_used or photo_id not in used_photo_ids:
                return photo
        return None

    for placeholder, slot in slot_map.items():
        orientation = _orientation_for_slot(slot, template_name)
        queries = _build_slot_queries(data, theme, slot)
        if slot in PALETTE_SLOTS:
            queries = queries[:MAX_QUERIES_PALETTE_SLOT]
        else:
            queries = queries[:MAX_QUERIES_SERVICE_SLOT]
        slot_colors = search_colors if slot in PALETTE_SLOTS else [None]
        slot_results: List[dict] = []

        selected = None
        if theme == "beauty-salon":
            strict_min_score = 24.0 if slot in PALETTE_SLOTS else 8.0
            fallback_min_score = 4.0 if slot in PALETTE_SLOTS else 0.0
        else:
            strict_min_score = 0.0
            fallback_min_score = 0.0
        for query in queries:
            for color in slot_colors:
                color_key = color or "any"
                cache_key = f"{orientation}|{color_key}|{query}"
                if cache_key not in query_cache:
                    query_cache[cache_key] = _search_pexels(
                        access_key,
                        query,
                        orientation,
                        color=color,
                    )
                slot_results.extend(query_cache[cache_key])
                selected = pick_from_results(
                    query_cache[cache_key],
                    slot=slot,
                    allow_used=False,
                    min_score=strict_min_score,
                    max_ratio_delta=0.45,
                )
                if selected:
                    break
            if selected:
                break

        # Broad fallback for this slot/theme.
        if not selected:
            broad_query = THEME_BASE_QUERIES.get(theme, THEME_BASE_QUERIES[DEFAULT_THEME])
            for color in slot_colors:
                color_key = color or "any"
                broad_key = f"{orientation}|{color_key}|{broad_query}"
                if broad_key not in query_cache:
                    query_cache[broad_key] = _search_pexels(
                        access_key,
                        broad_query,
                        orientation,
                        color=color,
                    )
                slot_results.extend(query_cache[broad_key])
                selected = pick_from_results(
                    query_cache[broad_key],
                    slot=slot,
                    allow_used=False,
                    min_score=fallback_min_score,
                    max_ratio_delta=0.65,
                )
                if selected:
                    break

        # Pool fallback: any previously fetched but unused image.
        if not selected:
            selected = pick_from_results(
                slot_results,
                slot=slot,
                allow_used=False,
                min_score=fallback_min_score,
                max_ratio_delta=0.8,
            )

        # Last resort: allow reuse rather than returning no image.
        if not selected:
            selected = pick_from_results(slot_results, slot=slot, allow_used=True)

        if selected:
            photo_id = selected.get("id")
            if photo_id:
                used_photo_ids.add(photo_id)
            url = _pexels_image_url(selected, slot, template_name=template_name)
            if url:
                suggestions[placeholder] = url

    return suggestions
