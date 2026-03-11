#!/usr/bin/env python3
"""
Shared website generation utilities.

Provides common helpers used across all website-building skills:
- Template copying
- Placeholder replacement (Mustache-style {{KEY}})
- Output validation
"""

import os
import re
import shutil
from pathlib import Path


def copy_template(template_dir: str, output_dir: str, overwrite: bool = False) -> str:
    """
    Copy a template directory to an output location.

    Args:
        template_dir: Path to the template directory (with index.html, styles.css, assets/).
        output_dir: Path where the website should be generated.
        overwrite: If True, remove existing output_dir before copying.

    Returns:
        Absolute path to the output directory.

    Raises:
        FileExistsError: If output_dir exists and overwrite is False.
        FileNotFoundError: If template_dir doesn't exist.
    """
    template_path = Path(template_dir).resolve()
    output_path = Path(output_dir).resolve()

    if not template_path.exists():
        raise FileNotFoundError(f"Template directory not found: {template_path}")

    if output_path.exists():
        if overwrite:
            shutil.rmtree(output_path)
        else:
            raise FileExistsError(
                f"Output directory already exists: {output_path}. "
                f"Use overwrite=True to replace it."
            )

    shutil.copytree(template_path, output_path)
    print(f"Copied template to {output_path}")
    return str(output_path)


def fill_template(content: str, data: dict) -> str:
    """
    Replace all {{PLACEHOLDER}} markers in content with values from data.

    Supports nested keys with dot notation (e.g., {{contact.phone}}).
    Missing keys are replaced with empty string by default.

    Args:
        content: Template string containing {{PLACEHOLDER}} markers.
        data: Dictionary mapping placeholder names to values.

    Returns:
        Content with all placeholders replaced.
    """
    def replace_match(match):
        key = match.group(1).strip()

        # Support nested keys: "contact.phone" -> data["contact"]["phone"]
        value = data
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part, "")
            else:
                value = ""
                break

        # Convert non-string values
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value if v)
        return str(value)

    # Match {{KEY}} with optional whitespace inside braces
    pattern = r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}"
    return re.sub(pattern, replace_match, content)


def fill_directory(directory: str, data: dict, file_extensions: tuple = (".html", ".css", ".js")) -> dict:
    """
    Replace placeholders in all matching files within a directory.

    Args:
        directory: Path to the directory to process.
        data: Dictionary mapping placeholder names to values.
        file_extensions: Tuple of file extensions to process.

    Returns:
        Dict with file paths as keys and number of replacements as values.
    """
    results = {}
    dir_path = Path(directory)

    for file_path in dir_path.rglob("*"):
        if file_path.is_file() and file_path.suffix in file_extensions:
            original = file_path.read_text(encoding="utf-8")
            filled = fill_template(original, data)

            # Count replacements
            original_count = len(re.findall(r"\{\{[A-Za-z0-9_.]+\}\}", original))
            remaining_count = len(re.findall(r"\{\{[A-Za-z0-9_.]+\}\}", filled))
            replacements = original_count - remaining_count

            file_path.write_text(filled, encoding="utf-8")
            results[str(file_path)] = replacements

    return results


def validate_output(directory: str, file_extensions: tuple = (".html", ".css", ".js")) -> dict:
    """
    Check that all placeholders have been replaced in the output.

    Args:
        directory: Path to the generated website directory.
        file_extensions: Tuple of file extensions to check.

    Returns:
        Dict with:
            - "valid": bool (True if no unfilled placeholders remain)
            - "unfilled": list of (file, placeholder) tuples
            - "files_checked": number of files checked
    """
    unfilled = []
    files_checked = 0
    dir_path = Path(directory)

    for file_path in dir_path.rglob("*"):
        if file_path.is_file() and file_path.suffix in file_extensions:
            files_checked += 1
            content = file_path.read_text(encoding="utf-8")
            matches = re.findall(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", content)
            for match in matches:
                unfilled.append((str(file_path.relative_to(dir_path)), match))

    return {
        "valid": len(unfilled) == 0,
        "unfilled": unfilled,
        "files_checked": files_checked,
    }
