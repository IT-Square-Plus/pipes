"""MarkdownReporter — generates promotion summary in markdown format."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PreCheckResult:
    """Aggregated data collected during the precheck phase."""

    version: str = ""
    instance: str = ""
    source_branch: str = ""
    target_branch: str = ""
    source_env: str = ""
    target_env: str = ""
    source_sha: str = ""
    target_sha: str = ""
    commit_count: str = "0"
    since_ref: str = ""
    last_author: str = ""
    last_date: str = ""
    last_message: str = ""
    changes_status: str = ""
    tag_status: str = ""
    target_tag_status: str = ""
    version_status: str = ""
    commit_log: str = ""
    diff_stat: str = ""
    files_changed: str = ""
    repo_clone_url: str = ""


class MarkdownReporter:
    """Generate a promotion summary markdown document."""

    @staticmethod
    def render(result: PreCheckResult) -> str:
        """Render *result* into a markdown string."""
        lines = [
            "| Detail | Value |",
            "|--------|-------|",
            f"| **Version** | `{result.version}` |",
            f"| **Instance** | `{result.instance}` |",
            f"| **Source** | `{result.source_env}` |",
            f"| **Target** | `{result.target_env}` |",
            f"| **Source commit** | `{result.source_sha[:8]}` |",
            f"| **Target commit** | `{result.target_sha[:8]}` |",
            f"| **Commits to promote** | {result.commit_count} ({result.since_ref}) |",
            f"| **Last author** | `{result.last_author}` |",
            f"| **Last commit date** | {result.last_date} |",
            f"| **Last commit message** | {result.last_message} |",
            "",
            "---",
            "",
            "### Status",
            f"- {result.changes_status}",
            f"- {result.tag_status}",
            f"- {result.target_tag_status}",
        ]

        if result.version_status:
            lines.append(f"- {result.version_status}")

        # Normalize diff stat — strip inconsistent leading spaces from git output
        diff_stat = result.diff_stat or "(no diff)"
        diff_stat = "\n".join(line.strip() for line in diff_stat.splitlines())

        lines += [
            "",
            "### \U0001f4dd Commits",
            "```",
            result.commit_log or "(no commits)",
            "```",
            "",
            "### \U0001f4ca Diff Stats",
            "```",
            diff_stat,
            "```",
            "",
            "### \U0001f4c1 Changed Files",
            "```",
            result.files_changed or "(no changes)",
            "```",
        ]

        if result.repo_clone_url:
            diff_cmd = (
                f"git diff origin/{result.target_branch}"
                f"..origin/{result.source_branch}"
            )
            lines += [
                "",
                "---",
                "",
                "### \U0001f50d Local Verification",
                "",
                "To review changes locally using Git CLI:",
                "",
                "```bash",
                f"git clone {result.repo_clone_url}",
                "git fetch origin",
                f"{diff_cmd}",
                "```",
            ]

        return "\n".join(lines) + "\n"
