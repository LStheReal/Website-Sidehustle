#!/usr/bin/env python3
"""
Helpers for storing generated client websites in a consistent folder structure.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


CLIENT_WEBSITES_DIRNAME = "freshNew_Client_Websiten"


def sanitize_path_component(value: str, fallback: str = "client") -> str:
    """
    Convert arbitrary text to a filesystem-safe folder name.
    Keeps ASCII letters/numbers and single dashes.
    """
    raw = (value or "").strip()
    if not raw:
        raw = fallback

    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    safe = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return safe or fallback


def get_client_websites_root(project_root: str | Path) -> Path:
    """Return and ensure the root output directory for generated client websites."""
    root = Path(project_root).resolve() / CLIENT_WEBSITES_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_company_output_dir(project_root: str | Path, business_name: str) -> Path:
    """Return and ensure the company-specific output directory."""
    company_dir = get_client_websites_root(project_root) / sanitize_path_component(
        business_name, fallback="firma"
    )
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir


def get_design_output_dir(project_root: str | Path, business_name: str, template_name: str) -> Path:
    """Return the output directory for one template design of one company."""
    return get_company_output_dir(project_root, business_name) / sanitize_path_component(
        template_name, fallback="design"
    )


def get_order_output_dir(
    project_root: str | Path,
    business_name: str,
    lead_id: str,
    template_key: str,
) -> Path:
    """Return the output directory for a submitted order website."""
    order_folder = f"order-{sanitize_path_component(lead_id, fallback='lead')}-{sanitize_path_component(template_key, fallback='website')}"
    return get_company_output_dir(project_root, business_name) / order_folder


def resolve_order_site_dir(
    project_root: str | Path,
    business_name: str,
    lead_id: str,
    template_key: str = "",
) -> Path:
    """
    Resolve order site directory with backwards compatibility.
    Prefer new client folder path, fallback to legacy .tmp/order_<lead_id>.
    """
    new_path = get_order_output_dir(project_root, business_name, lead_id, template_key or "website")
    if (new_path / "index.html").exists():
        return new_path

    legacy_path = Path(project_root).resolve() / ".tmp" / f"order_{lead_id}"
    if (legacy_path / "index.html").exists():
        return legacy_path

    return new_path
