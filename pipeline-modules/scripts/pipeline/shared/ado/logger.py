"""Azure DevOps pipeline logging helpers.

Emits ##vso logging commands when running inside an ADO pipeline,
falls back to Rich-formatted output when running locally.
"""

from __future__ import annotations

import os
import sys

from shared.console import console


def is_pipeline() -> bool:
    """Return True if running inside an Azure DevOps pipeline."""
    return "BUILD_BUILDID" in os.environ


def error(message: str) -> None:
    """Emit an error. In ADO pipeline, uses ##[error]; otherwise Rich formatted."""
    if is_pipeline():
        print(f"##[error]{message}", flush=True)
    else:
        console.print(f"[bold red]ERROR[/bold red] {message}")


def warning(message: str) -> None:
    """Emit a warning. In ADO pipeline, uses ##[warning]; otherwise Rich formatted."""
    if is_pipeline():
        print(f"##[warning]{message}", flush=True)
    else:
        console.print(f"[bold yellow]WARN[/bold yellow]  {message}")


def info(message: str) -> None:
    """Print an informational message."""
    if is_pipeline():
        print(f"[INFO] {message}", flush=True)
    else:
        console.print(f"[bold blue]INFO[/bold blue]  {message}")


def success(message: str) -> None:
    """Print a success message."""
    if is_pipeline():
        print(f"[OK] {message}", flush=True)
    else:
        console.print(f"[bold green]OK[/bold green]    {message}")


def set_variable(name: str, value: str, is_output: bool = False) -> None:
    """Set an ADO pipeline variable."""
    if is_pipeline():
        output_flag = ";isOutput=true" if is_output else ""
        print(f"##vso[task.setvariable variable={name}{output_flag}]{value}", flush=True)


def add_build_tag(tag: str) -> None:
    """Add a build tag to the current pipeline run."""
    if is_pipeline():
        print(f"##vso[build.addbuildtag]{tag}", flush=True)


def upload_summary(file_path: str) -> None:
    """Upload a markdown summary file to ADO pipeline."""
    if is_pipeline():
        print(f"##vso[task.uploadsummary]{file_path}", flush=True)
