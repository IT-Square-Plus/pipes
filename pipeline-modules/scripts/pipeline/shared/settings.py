"""Shared settings loader — reads settings.yaml once and exposes values."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.yaml"
_cache: dict | None = None


def _load() -> dict:
    """Load and cache settings.yaml."""
    global _cache
    if _cache is not None:
        return _cache

    if not _SETTINGS_PATH.exists():
        print(f"ERROR: Settings file not found: {_SETTINGS_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(_SETTINGS_PATH, encoding="utf-8") as fh:
        _cache = yaml.safe_load(fh)
    return _cache


def org() -> str:
    """Azure DevOps organization name."""
    value = _load().get("org", "")
    if not value:
        print("ERROR: 'org' not defined in settings.yaml", file=sys.stderr)
        sys.exit(1)
    return value


def project() -> str:
    """Azure DevOps project name."""
    value = _load().get("project", "")
    if not value:
        print("ERROR: 'project' not defined in settings.yaml", file=sys.stderr)
        sys.exit(1)
    return value


def approvers() -> list[dict]:
    """Approvers list in ADO format (displayName + id)."""
    section = _load().get("approvers", {})
    raw = section.get("list", []) if isinstance(section, dict) else section
    if not raw:
        print("ERROR: No approvers defined in settings.yaml", file=sys.stderr)
        sys.exit(1)
    return [{"displayName": a["name"], "id": a["id"]} for a in raw]


def min_approvers(env: str) -> int:
    """Minimum required approvers for a given environment (defaults to 1)."""
    section = _load().get("approvers", {})
    if not isinstance(section, dict):
        return 1
    minimum = section.get("minimum", {})
    return int(minimum.get(env, 1))
