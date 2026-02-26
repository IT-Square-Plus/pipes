"""Shared Rich console instance for the pipeline package."""

from __future__ import annotations

from rich.console import Console

# Single shared console instance — all commands use this
console = Console()
