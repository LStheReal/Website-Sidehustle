#!/usr/bin/env python3
from __future__ import annotations

"""Template-aware copy enrichment for generated websites.

Uses Claude Haiku AI for text generation when ANTHROPIC_API_KEY is available,
falls back to rule-based enrichment otherwise.
"""

import json
import os
import re
from typing import Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def enrich_with_ai(data: Dict[str, str], template_name: str) -> Dict[str, str]:
    """Use Claude Haiku to generate professional website copy from business info.

    Returns dict of placeholder -> generated text. Returns empty dict if API unavailable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}

    name = data.get("BUSINESS_NAME", "")
    category = data.get("category", "") or data.get("CATEGORY", "") or data.get("BUSINESS_CATEGORY", "")
    city = data.get("city", "") or data.get("CITY", "") or data.get("BUSINESS_CITY", "")
    description = data.get("HERO_DESCRIPTION", "") or data.get("ABOUT_DESCRIPTION", "")
    services = []
    for i in range(1, 7):
        t = data.get(f"SERVICE_{i}_TITLE", "")
        if t and t not in (f"Service {i}", f"Leistung {i}"):
            services.append(t)

    if not description and not services and not category:
        return {}

    context_parts = []
    if name:
        context_parts.append(f"Firmenname: {name}")
    if category:
        context_parts.append(f"Branche: {category}")
    if city:
        context_parts.append(f"Standort: {city}")
    if description:
        context_parts.append(f"Beschreibung: {description}")
    if services:
        context_parts.append(f"Leistungen/Werte: {', '.join(services)}")
    context = "\n".join(context_parts)

    prompt = f"""Du bist ein Webseiten-Texter für Schweizer KMU. Erstelle professionelle, authentische deutsche Texte für eine Firmenwebsite.

Firma-Info:
{context}

Generiere ein JSON-Objekt mit diesen Feldern. Jeder Text soll einzigartig sein, zur Firma passen und NICHT einfach die Beschreibung wiederholen. Schreibe natürlich und professionell auf Deutsch (Schweizer Stil, kein ß).

{{
  "TAGLINE": "kurzer Slogan, max 8 Wörter",
  "HERO_TITLE_LINE1": "erste Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE2": "zweite Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE3": "dritte Zeile oder leer",
  "HERO_DESCRIPTION": "1-2 Sätze, was die Firma bietet, max 150 Zeichen",
  "ABOUT_HEADING": "Überschrift Über-uns-Bereich, 2-4 Wörter",
  "ABOUT_LEAD": "1 Satz Einleitung zum Über-uns-Text, max 100 Zeichen",
  "ABOUT_DESCRIPTION": "2-3 Sätze über die Firma, Werte und Arbeitsweise",
  "INTRO_TEXT": "kurze Einleitung, 3-5 Wörter",
  "INTRO_DESCRIPTION": "1 Satz Firmenbeschreibung, max 120 Zeichen",
  "FEATURE_HEADING": "Überschrift Vorteile-Bereich, 2-4 Wörter",
  "FEATURE_DESCRIPTION": "1 Satz warum diese Firma, max 100 Zeichen",
  "FEATURE_POINT_1": "Vorteil 1, 2-3 Wörter",
  "FEATURE_POINT_2": "Vorteil 2, 2-3 Wörter",
  "FEATURE_POINT_3": "Vorteil 3, 2-3 Wörter",
  "SERVICE_1_TITLE": "Leistung 1 Name",
  "SERVICE_1_DESCRIPTION": "1 Satz zu Leistung 1",
  "SERVICE_2_TITLE": "Leistung 2 Name",
  "SERVICE_2_DESCRIPTION": "1 Satz zu Leistung 2",
  "SERVICE_3_TITLE": "Leistung 3 Name",
  "SERVICE_3_DESCRIPTION": "1 Satz zu Leistung 3",
  "CTA_DESCRIPTION": "Handlungsaufforderung, 1 Satz",
  "CTA_TITLE_LINE1": "CTA Titel Zeile 1, 2-3 Wörter",
  "CTA_TITLE_LINE2": "CTA Titel Zeile 2, 2-3 Wörter",
  "VALUE_1_TITLE": "Wert 1, 1-2 Wörter",
  "VALUE_1_DESCRIPTION": "kurze Beschreibung Wert 1",
  "VALUE_2_TITLE": "Wert 2, 1-2 Wörter",
  "VALUE_2_DESCRIPTION": "kurze Beschreibung Wert 2",
  "VALUE_3_TITLE": "Wert 3, 1-2 Wörter",
  "VALUE_3_DESCRIPTION": "kurze Beschreibung Wert 3",
  "STATEMENT_LINE1": "Statement Zeile 1, 2-4 Wörter",
  "STATEMENT_LINE2": "Statement Zeile 2, 2-4 Wörter",
  "STATEMENT_LINE3": "Statement Zeile 3, 2-4 Wörter",
  "META_DESCRIPTION": "SEO-Beschreibung, max 155 Zeichen"
}}

Antworte NUR mit dem JSON-Objekt, kein anderer Text."""

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            }).encode(),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        text = "".join(b.get("text", "") for b in result.get("content", []))
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        return json.loads(match.group(0))
    except Exception as e:
        print(f"[copy_enrichment] AI enrichment failed: {e}")
        return {}


def _clean(text: str) -> str:
    text = (text or "").lower()
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        .replace("é", "e")
        .replace("è", "e")
        .replace("à", "a")
        .replace("ç", "c")
    )
    text = re.sub(r"[^a-z0-9aeiou\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_keyword(haystack: str, keyword: str) -> bool:
    token = (keyword or "").strip().lower()
    if not token:
        return False
    if len(token) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack))
    return token in haystack


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def _is_short(text: str, min_words: int) -> bool:
    return not (text or "").strip() or _word_count(text) < min_words


def _theme_from_data(data: Dict[str, str]) -> str:
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

    if any(_has_keyword(haystack, k) for k in ("coiffeur", "friseur", "barber", "salon", "beauty", "kosmetik", "nail")):
        return "beauty"
    if any(_has_keyword(haystack, k) for k in ("arzt", "zahnarzt", "praxis", "therapie", "medical", "clinic")):
        return "medical"
    if any(_has_keyword(haystack, k) for k in ("maler", "elektr", "sanita", "schreiner", "renov", "bau", "plumber")):
        return "trade"
    if any(_has_keyword(haystack, k) for k in ("it", "software", "digital", "agentur", "agency", "web", "saas")):
        return "tech"
    return "local"


def _service_sentence(theme: str, title: str, city: str) -> str:
    title_clean = (title or "Leistung").strip()
    city_bit = f" in {city}" if city else ""
    if theme == "beauty":
        return (
            f"Mit {title_clean} begleiten wir Sie persoenlich{city_bit}, "
            f"mit einem klaren Blick auf Stil, Pflege und Alltagstauglichkeit."
        )
    if theme == "medical":
        return (
            f"{title_clean} bedeutet bei uns strukturierte Ablaeufe, "
            f"transparente Beratung und eine ruhige, verlaessliche Betreuung."
        )
    if theme == "tech":
        return (
            f"{title_clean} setzen wir praxisnah um, mit klaren Prozessen, "
            f"messbaren Ergebnissen und fester Ansprechperson."
        )
    if theme == "trade":
        return (
            f"Bei {title_clean} achten wir auf saubere Ausfuehrung, termintreue Planung "
            f"und nachvollziehbare Kosten fuer Ihr Projekt."
        )
    return (
        f"{title_clean} liefern wir zuverlaessig und individuell, "
        f"damit Sie eine Loesung erhalten, die langfristig wirklich passt."
    )


def _set_if_short(target: Dict[str, str], key: str, value: str, min_words: int) -> None:
    if _is_short(str(target.get(key, "")), min_words):
        target[key] = value


def _contains_marker(text: str, marker: str) -> bool:
    return _clean(marker) in _clean(text)


def _set_if_short_or_placeholder(
    target: Dict[str, str],
    key: str,
    value: str,
    min_words: int,
    markers: tuple[str, ...] = (),
) -> None:
    current = str(target.get(key, ""))
    if _is_short(current, min_words) or any(_contains_marker(current, m) for m in markers):
        target[key] = value


def _looks_like_painter(data: Dict[str, str]) -> bool:
    haystack = _clean(
        " ".join(
            [
                str(data.get("BUSINESS_CATEGORY", "")),
                str(data.get("CATEGORY", "")),
                str(data.get("category", "")),
                str(data.get("TAGLINE", "")),
                str(data.get("SEARCH_QUERY", "")),
                str(data.get("BUSINESS_NAME", "")),
            ]
        )
    )
    return any(
        _has_keyword(haystack, kw)
        for kw in ("maler", "malerei", "anstrich", "fassade", "gipser", "stuck", "tapezier")
    )


def _clean_title(value: str) -> str:
    text = _clean(value)
    text = text.replace(" ", "")
    return text


def _is_generic_service_title(value: str, index: int) -> bool:
    token = _clean_title(value)
    generic = {
        "",
        f"service{index}",
        f"leistung{index}",
        "beratung",
        "planung",
        "umsetzung",
        "ausfuehrung",
        "betreuung",
        "entwicklung",
        "sicherheit",
        "support",
        "schulung",
        "qualitat",
        "qualitaet",
        "qualitt",
        "qualität",
        "feinschliff",
    }
    return token in generic


def _set_service_title_if_generic(target: Dict[str, str], key: str, value: str, index: int) -> None:
    current = str(target.get(key, ""))
    if _is_generic_service_title(current, index):
        target[key] = value


def _set_if_missing_or_fake_stat(target: Dict[str, str], key: str, value: str) -> None:
    current = str(target.get(key, "")).strip()
    fake_defaults = {
        "",
        "10+",
        "12",
        "15+",
        "50+",
        "100%",
        "200+",
        "500+",
        "Jahre Erfahrung",
        "Zufriedene Kunden",
        "Projekte pro Jahr",
        "Engagement",
        "Projekte realisiert",
        "Einsatz",
    }
    if current in fake_defaults:
        target[key] = value


def enrich_template_copy(data: Dict[str, str], template_name: str) -> Dict[str, str]:
    """Expand short copy fields so generated pages feel complete and substantial.

    Uses AI enrichment first (Claude Haiku), then fills remaining gaps with rules.
    """
    enriched = dict(data)

    # AI enrichment: generate unique copy based on business info
    ai_text = enrich_with_ai(enriched, template_name)
    for key, value in ai_text.items():
        if value and not key.startswith("IMAGE_"):
            # AI overrides defaults but not user-provided data
            current = enriched.get(key, "")
            is_default = not current or current in (
                f"Service {key[-1]}" if key.startswith("SERVICE_") and key.endswith("_TITLE") else "",
                f"Leistung {key[-1]}" if key.startswith("SERVICE_") and key.endswith("_TITLE") else "",
            )
            if is_default or not current.strip():
                enriched[key] = value

    template = (template_name or "").strip().lower()

    business_name = str(enriched.get("BUSINESS_NAME", "Unser Unternehmen")).strip()
    category = str(
        enriched.get("BUSINESS_CATEGORY")
        or enriched.get("CATEGORY")
        or enriched.get("category")
        or "Dienstleistungen"
    ).strip()
    city = str(enriched.get("BUSINESS_CITY") or enriched.get("CITY") or enriched.get("city") or "").strip()
    city_bit = f" in {city}" if city else ""
    theme = _theme_from_data(enriched)

    if template == "earlydog":
        if theme == "trade":
            painter_mode = _looks_like_painter(enriched)
            earlydog_titles = (
                ["Innenanstriche", "Fassadenanstriche", "Renovationsarbeiten"]
                if painter_mode
                else ["Beratung vor Ort", "Fachgerechte Ausfuehrung", "Saubere Abnahme"]
            )
            for idx, title in enumerate(earlydog_titles, start=1):
                _set_service_title_if_generic(enriched, f"SERVICE_{idx}_TITLE", title, idx)

        _set_if_short(
            enriched,
            "HERO_DESCRIPTION",
            f"{business_name} steht fuer {category}{city_bit} mit persoenlicher Beratung, klaren Ablaufen und verlaesslicher Umsetzung. "
            f"Wir nehmen uns Zeit fuer Ihre Wuensche und liefern Ergebnisse, die im Alltag funktionieren.",
            16,
        )
        for i in ("1", "2", "3"):
            title = str(enriched.get(f"SERVICE_{i}_TITLE", f"Leistung {i}"))
            _set_if_short(enriched, f"SERVICE_{i}_DESCRIPTION", _service_sentence(theme, title, city), 14)

    if template == "bia":
        if theme == "trade":
            painter_mode = _looks_like_painter(enriched)
            bia_titles = (
                [
                    "Farbberatung",
                    "Innenanstriche",
                    "Fassadenanstriche",
                    "Tapezierarbeiten",
                ]
                if painter_mode
                else [
                    "Beratung vor Ort",
                    "Planung",
                    "Fachgerechte Ausfuehrung",
                    "Saubere Abnahme",
                ]
            )
            for idx, title in enumerate(bia_titles, start=1):
                _set_service_title_if_generic(enriched, f"SERVICE_{idx}_TITLE", title, idx)

        _set_if_short(
            enriched,
            "INTRO_TEXT",
            f"Als Partner fuer {category}{city_bit} verbinden wir Erfahrung, praezise Planung und ein klares Qualitaetsversprechen. "
            f"Jedes Projekt wird strukturiert gefuehrt und konsequent auf Ihren Bedarf ausgerichtet.",
            20,
        )
        _set_if_short(
            enriched,
            "INTRO_DESCRIPTION",
            f"Von der ersten Idee bis zur finalen Umsetzung begleitet Sie {business_name} mit festen Ansprechpersonen, "
            f"transparenten Schritten und sauberer Kommunikation. So entstehen Ergebnisse, die gestalterisch ueberzeugen und technisch tragen.",
            22,
        )
        for i in ("1", "2", "3", "4"):
            title = str(enriched.get(f"SERVICE_{i}_TITLE", f"Leistung {i}"))
            _set_if_short(enriched, f"SERVICE_{i}_DESCRIPTION", _service_sentence(theme, title, city), 14)

        if theme == "trade":
            _set_if_missing_or_fake_stat(enriched, "STAT_1_NUMBER", "Sauber")
            _set_if_missing_or_fake_stat(enriched, "STAT_1_LABEL", "Ausfuehrung")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_NUMBER", "Termintreu")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_LABEL", "Planung")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_NUMBER", "Transparent")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_LABEL", "Ablaeufe")
        else:
            _set_if_missing_or_fake_stat(enriched, "STAT_1_NUMBER", "Praxisnah")
            _set_if_missing_or_fake_stat(enriched, "STAT_1_LABEL", "Loesungen")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_NUMBER", "Zuverlaessig")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_LABEL", "Ablauf")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_NUMBER", "Persoenlich")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_LABEL", "Betreuung")

        _set_if_short(
            enriched,
            "ABOUT_DESCRIPTION",
            f"{business_name} arbeitet mit einem hohen Anspruch an Qualitaet, Verlaesslichkeit und Wirkung. "
            f"Wir denken Projekte ganzheitlich, stimmen Details frueh ab und sorgen fuer ein Ergebnis, das langfristig Bestand hat.",
            22,
        )

    if template == "liveblocks":
        painter_mode = theme == "trade" and _looks_like_painter(enriched)
        if theme == "trade":
            liveblocks_titles = (
                [
                    "Farbberatung",
                    "Innenanstriche",
                    "Fassadenanstriche",
                    "Tapezierarbeiten",
                    "Gipserarbeiten",
                    "Schutzanstriche",
                ]
                if painter_mode
                else [
                    "Beratung vor Ort",
                    "Planung",
                    "Ausfuehrung",
                    "Unterhalt",
                    "Abnahme",
                    "Kundenservice",
                ]
            )
            for idx, title in enumerate(liveblocks_titles, start=1):
                _set_service_title_if_generic(enriched, f"SERVICE_{idx}_TITLE", title, idx)

        _set_if_short(
            enriched,
            "HERO_DESCRIPTION",
            f"Wir unterstuetzen Unternehmen{city_bit} mit einem klaren Fahrplan, sauberer Umsetzung und messbarem Fortschritt. "
            f"Von der Strategie bis zum Betrieb erhalten Sie einen Partner, der schnell reagiert und Verantwortung uebernimmt.",
            20,
        )
        _set_if_short_or_placeholder(
            enriched,
            "SERVICES_DESCRIPTION",
            (
                "Unser Leistungsspektrum deckt Vorbereitung, Ausfuehrung und sauberen Abschluss ab. "
                "Wir arbeiten klar strukturiert, termintreu und mit hoher Sorgfalt bis ins Detail."
                if theme == "trade"
                else "Unser Leistungsportfolio deckt Beratung, Umsetzung und laufende Betreuung ab. "
                "Dabei verbinden wir Struktur, Effizienz und hohe Qualitaetsstandards in jedem Schritt."
            ),
            18,
            markers=(
                "Unser Leistungsportfolio deckt Beratung, Umsetzung und laufende Betreuung ab",
            ),
        )
        for i in ("1", "2", "3", "4", "5", "6"):
            title = str(enriched.get(f"SERVICE_{i}_TITLE", f"Leistung {i}"))
            _set_if_short(enriched, f"SERVICE_{i}_DESCRIPTION", _service_sentence(theme, title, city), 14)

        if painter_mode:
            painter_service_copy = {
                "SERVICE_1_DESCRIPTION": (
                    "Wir beraten Sie zu Farbkonzepten, Materialwahl und Untergrund, damit das Resultat fachlich und optisch passt."
                ),
                "SERVICE_2_DESCRIPTION": (
                    "Innenwaende, Decken und Details streichen wir praezise, sauber abgeklebt und abgestimmt auf Ihre Raeume."
                ),
                "SERVICE_3_DESCRIPTION": (
                    "Fassaden beschichten wir wetterbestaendig und langlebig, inklusive sorgfaeltiger Vorbehandlung der Flaechen."
                ),
                "SERVICE_4_DESCRIPTION": (
                    "Tapeten entfernen, Untergruende vorbereiten und neue Bahnen sauber setzen - mit ruhigem, exaktem Ablauf."
                ),
                "SERVICE_5_DESCRIPTION": (
                    "Risse schliessen, Flaechen spachteln und sauber glätten als solide Basis fuer hochwertige Endanstriche."
                ),
                "SERVICE_6_DESCRIPTION": (
                    "Treppenhaeuser, Holzbauteile und stark beanspruchte Zonen schuetzen wir mit robusten, passenden Anstrichsystemen."
                ),
            }
            for key, value in painter_service_copy.items():
                _set_if_short(enriched, key, value, 16)

        if theme == "trade":
            _set_if_missing_or_fake_stat(enriched, "STAT_1_NUMBER", "Sauber")
            _set_if_missing_or_fake_stat(enriched, "STAT_1_LABEL", "Ausfuehrung")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_NUMBER", "Termintreu")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_LABEL", "Planung")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_NUMBER", "Transparent")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_LABEL", "Angebote")
            _set_if_missing_or_fake_stat(enriched, "STAT_4_NUMBER", "Persoenlich")
            _set_if_missing_or_fake_stat(enriched, "STAT_4_LABEL", "Betreuung")
        else:
            _set_if_missing_or_fake_stat(enriched, "STAT_1_NUMBER", "Praxisnah")
            _set_if_missing_or_fake_stat(enriched, "STAT_1_LABEL", "Loesungen")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_NUMBER", "Zuverlaessig")
            _set_if_missing_or_fake_stat(enriched, "STAT_2_LABEL", "Ablauf")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_NUMBER", "Persoenlich")
            _set_if_missing_or_fake_stat(enriched, "STAT_3_LABEL", "Betreuung")
            _set_if_missing_or_fake_stat(enriched, "STAT_4_NUMBER", "Transparent")
            _set_if_missing_or_fake_stat(enriched, "STAT_4_LABEL", "Kommunikation")

        _set_if_short(
            enriched,
            "FEATURE_DESCRIPTION",
            f"Mit klaren Prozessen, definierten Zuständigkeiten und regelmaessigen Updates bleibt Ihr Projekt jederzeit steuerbar. "
            f"So erreichen wir verlässlich ein Ergebnis, das fachlich und wirtschaftlich passt.",
            20,
        )
        if theme == "trade":
            _set_if_short_or_placeholder(
                enriched,
                "FEATURE_HEADING",
                "Saubere Resultate durch klare Arbeitsablaeufe",
                8,
                markers=("Erstklassige Ergebnisse durch bewährte Methoden",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "FEATURE_POINT_1",
                "Sorgfaeltige Vorbereitung der Flaechen vor jedem Anstrich",
                8,
                markers=("Individuelle Lösungen, massgeschneidert auf Ihre Bedürfnisse",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "FEATURE_POINT_2",
                "Transparente Offerten und laufende Abstimmung waehrend der Ausfuehrung",
                8,
                markers=("Transparente Kommunikation und regelmässige Updates",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "FEATURE_POINT_3",
                "Termintreue Umsetzung mit sauberer Abnahme und klarer Dokumentation",
                8,
                markers=("Langfristige Partnerschaft statt einmaliger Zusammenarbeit",),
            )
        _set_if_short_or_placeholder(
            enriched,
            "ABOUT_LEAD",
            (
                f"Hinter {business_name} steht ein Team, das sauber arbeitet, Absprachen einhaelt und Verantwortung bis zur Abnahme uebernimmt."
                if theme == "trade"
                else f"Hinter {business_name} steht ein Team, das Verantwortung uebernimmt und Projekte mit Fokus auf Wirkung umsetzt."
            ),
            14,
            markers=("Wir sind ein engagiertes Team von Experten",),
        )
        _set_if_short_or_placeholder(
            enriched,
            "ABOUT_DESCRIPTION",
            (
                f"Von der ersten Besichtigung bis zur finalen Ausfuehrung begleiten wir Projekte{city_bit} mit klaren Schritten, "
                "transparenter Kommunikation und sauberer Arbeitsweise. Unsere Kunden schaetzen Termintreue, "
                "zuverlaessige Umsetzung und nachvollziehbare Angebote."
                if theme == "trade"
                else "Wir arbeiten partnerschaftlich, denken in Loesungen und setzen auf langfristige Zusammenarbeit. "
                "Unsere Kunden schaetzen die Mischung aus fachlicher Tiefe, klarer Kommunikation und hoher Termintreue."
            ),
            20,
            markers=(
                "Seit unserer Gründung arbeiten wir eng mit unseren Kunden zusammen",
                "Unser Ansatz verbindet bewährte Methoden mit innovativem Denken",
            ),
        )
        _set_if_short(
            enriched,
            "CTA_DESCRIPTION",
            "Lassen Sie uns in einem unverbindlichen Erstgespraech Ihre Ziele, Prioritaeten und naechsten Schritte strukturieren. "
            "Sie erhalten eine klare Empfehlung und einen realistischen Umsetzungsplan.",
            20,
        )
        _set_if_short(
            enriched,
            "CONTACT_CARD_1_DESCRIPTION",
            "Sprechen Sie direkt mit uns und erhalten Sie eine schnelle erste Einschaetzung zu Ihrem Anliegen.",
            14,
        )
        _set_if_short(
            enriched,
            "CONTACT_CARD_2_DESCRIPTION",
            "Schreiben Sie uns kurz Ihr Ziel und wir melden uns zeitnah mit einem konkreten Vorschlag zur weiteren Vorgehensweise.",
            16,
        )

        if theme == "trade":
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_1_TITLE",
                "Saubere Ausfuehrung",
                2,
                markers=("Qualität",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_1_DESCRIPTION",
                "Wir arbeiten praezise, schuetzen Oberflaechen konsequent und liefern ein ordentliches Endresultat.",
                12,
                markers=("Wir setzen auf höchste Qualitätsstandards bei jedem Projekt",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_2_TITLE",
                "Termintreue Planung",
                2,
                markers=("Innovation",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_2_DESCRIPTION",
                "Ablauf, Material und Ausfuehrung stimmen wir frueh ab, damit Ihr Projekt planbar bleibt.",
                12,
                markers=("Neue Wege gehen und kreative Lösungen finden",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_3_TITLE",
                "Transparente Angebote",
                2,
                markers=("Vertrauen",),
            )
            _set_if_short_or_placeholder(
                enriched,
                "VALUE_3_DESCRIPTION",
                "Sie erhalten nachvollziehbare Offerten, klare Positionen und ehrliche Empfehlungen.",
                10,
                markers=("Langfristige Kundenbeziehungen basieren auf gegenseitigem Vertrauen",),
            )

            if _is_generic_service_title(str(enriched.get("FOOTER_COL_1_LINK_1", "")), 1):
                enriched["FOOTER_COL_1_LINK_1"] = str(enriched.get("SERVICE_1_TITLE", "Leistung 1"))
            if _is_generic_service_title(str(enriched.get("FOOTER_COL_1_LINK_2", "")), 2):
                enriched["FOOTER_COL_1_LINK_2"] = str(enriched.get("SERVICE_2_TITLE", "Leistung 2"))
            if _is_generic_service_title(str(enriched.get("FOOTER_COL_1_LINK_3", "")), 3):
                enriched["FOOTER_COL_1_LINK_3"] = str(enriched.get("SERVICE_3_TITLE", "Leistung 3"))

    if template == "loveseen":
        if theme == "trade":
            painter_mode = _looks_like_painter(enriched)
            loveseen_titles = (
                ["Innenanstriche", "Fassadenanstriche", "Feinarbeiten & Finish"]
                if painter_mode
                else ["Beratung vor Ort", "Ausfuehrung", "Feinschliff"]
            )
            for idx, title in enumerate(loveseen_titles, start=1):
                _set_service_title_if_generic(enriched, f"SERVICE_{idx}_TITLE", title, idx)

        if theme == "beauty":
            about_lead = (
                f"Bei {business_name} verbinden wir Stilgefuehl, Praezision und persoenliche Beratung fuer Ergebnisse, die echt zu Ihnen passen."
            )
            about_description = (
                f"Unser Studio{city_bit} steht fuer ein ruhiges, hochwertiges Erlebnis mit klarer Handschrift. "
                f"Wir nehmen uns Zeit fuer Ihre Wuensche, arbeiten sauber bis ins Detail und schaffen Looks, die auch nach dem Termin ueberzeugen."
            )
        elif theme == "trade":
            about_lead = (
                f"Bei {business_name} verbinden wir handwerkliche Praezision, termintreue Planung und eine saubere Ausfuehrung."
            )
            about_description = (
                f"Als Team fuer {category}{city_bit} begleiten wir Projekte strukturiert von der Besichtigung bis zur Abnahme. "
                f"Wir arbeiten zuverlaessig, halten Absprachen ein und liefern Resultate, die langlebig und hochwertig sind."
            )
        elif theme == "medical":
            about_lead = (
                f"Bei {business_name} verbinden wir fachliche Sorgfalt, ruhige Ablaeufe und eine klare, transparente Beratung."
            )
            about_description = (
                f"Unsere Betreuung{city_bit} ist auf Sicherheit, Verstaendlichkeit und Verlaesslichkeit ausgerichtet. "
                f"Sie erhalten strukturierte Prozesse, feste Ansprechpersonen und nachvollziehbare Empfehlungen."
            )
        elif theme == "tech":
            about_lead = (
                f"Bei {business_name} verbinden wir praezise Planung, pragmatische Umsetzung und enge Zusammenarbeit."
            )
            about_description = (
                f"Wir begleiten Vorhaben{city_bit} mit klaren Prioritaeten, kurzen Wegen und messbaren Ergebnissen. "
                f"So entstehen Loesungen, die fachlich ueberzeugen und wirtschaftlich tragfaehig bleiben."
            )
        else:
            about_lead = (
                f"Bei {business_name} verbinden wir Qualitaet, Verlaesslichkeit und persoenliche Beratung fuer Ergebnisse mit Bestand."
            )
            about_description = (
                f"Unser Team{city_bit} arbeitet strukturiert, termintreu und mit viel Sorgfalt im Detail. "
                f"So entstehen Loesungen, die alltagstauglich sind und langfristig ueberzeugen."
            )

        _set_if_short(
            enriched,
            "ABOUT_LEAD",
            about_lead,
            16,
        )
        _set_if_short(
            enriched,
            "ABOUT_DESCRIPTION",
            about_description,
            22,
        )
        for i in ("1", "2", "3"):
            title = str(enriched.get(f"SERVICE_{i}_TITLE", f"Leistung {i}"))
            _set_if_short(enriched, f"SERVICE_{i}_DESCRIPTION", _service_sentence(theme, title, city), 14)
        _set_if_short(
            enriched,
            "CONTACT_TAGLINE",
            "Schreiben oder rufen Sie uns an, wir beraten Sie persoenlich und finden den Termin, der fuer Sie passt.",
            14,
        )

    return enriched
