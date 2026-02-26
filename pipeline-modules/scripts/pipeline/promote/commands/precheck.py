"""PreCheckCommand — gather promotion info and produce a summary."""

from __future__ import annotations

import os

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from shared.ado import logger
from promote.commands.base import BaseCommand
from shared.console import console
from promote.models.meta import MetaConfig
from promote.services.git import GitService
from promote.services.tag import TagService
from promote.services.version import VersionService
from promote.services.markdown import MarkdownReporter, PreCheckResult


class PreCheckCommand(BaseCommand):
    """Gather all promotion details and render a markdown summary."""

    def execute(self) -> int:
        ctx = self._ctx
        git = GitService(ctx.repo_dir)

        # 1. Fetch tags
        git.fetch_tags()

        # 2. Read meta.yaml from source branch
        meta = MetaConfig.read_from_branch(ctx.source_branch, git)
        ctx.version = meta["version"]
        ctx.instance = meta["instance"]
        ctx.compute_tags()

        # 3. Commit comparison
        source_sha = git.rev_parse(f"origin/{ctx.source_branch}")
        target_sha = git.rev_parse(f"origin/{ctx.target_branch}")

        # 4. Find last promotion tag on source branch
        last_source_tag = TagService.find_last_promotion_tag(
            git, ctx.source_branch, ctx.source_env, ctx.instance
        )
        if last_source_tag is None:
            # First promotion — try target tag pattern on target branch
            last_source_tag = TagService.find_last_promotion_tag(
                git, ctx.target_branch, ctx.target_env, ctx.instance
            )

        # 5. Version regression check
        version_status = ""
        if last_source_tag:
            last_version = TagService.extract_version_from_tag(last_source_tag)
            version_status = VersionService.check_regression(
                ctx.version, last_source_tag, last_version
            ) or ""

        # 6. Commit log
        if last_source_tag:
            ref_range = f"{last_source_tag}..origin/{ctx.source_branch}"
            commit_log = git.log("%h | %aI | %an <%ae> :: %s", ref_range)
            commit_count = git.rev_list_count(ref_range) or "0"
            since_ref = f"since tag {last_source_tag}"
        else:
            merge_base = git.merge_base(
                f"origin/{ctx.source_branch}", f"origin/{ctx.target_branch}"
            )
            if merge_base:
                ref_range = f"{merge_base}..origin/{ctx.source_branch}"
                commit_log = git.log("%h | %aI | %an <%ae> :: %s", ref_range)
                commit_count = git.rev_list_count(ref_range) or "0"
            else:
                commit_log = git.log(
                    "%h | %aI | %an <%ae> :: %s",
                    f"origin/{ctx.source_branch}",
                    max_count=20,
                )
                commit_count = "?"
            since_ref = "since branch creation (no previous tags)"

        # 7. Diff stats
        diff_range = f"origin/{ctx.target_branch}..origin/{ctx.source_branch}"
        diff_stat = git.diff_stat(diff_range)
        files_changed = git.diff_name_only(diff_range)

        # 8. Last commit info
        last_author = git.log("%an <%ae>", f"origin/{ctx.source_branch}", max_count=1)
        last_date = git.log("%ai", f"origin/{ctx.source_branch}", max_count=1)
        last_message = git.log("%s", f"origin/{ctx.source_branch}", max_count=1)

        # 9. Tag status checks
        if git.tag_exists(ctx.source_tag):
            tag_status = f"\u26a0\ufe0f Tag '{ctx.source_tag}' already exists (re-run)"
        else:
            tag_status = f"\U0001f3f7\ufe0f Will create tag '{ctx.source_tag}'"

        if git.tag_exists(ctx.target_tag):
            target_tag_status = f"\u274c Tag '{ctx.target_tag}' already exists \u2014 promotion will FAIL"
        else:
            target_tag_status = f"\U0001f3f7\ufe0f Will create tag '{ctx.target_tag}'"

        # 10. Changes detection
        if git.diff_quiet(diff_range):
            changes_status = "\u26a0\ufe0f **No changes detected** \u2014 source and target are identical"
        else:
            changes_status = f"\u2705 Changes detected ({commit_count} commit{'s' if commit_count != '1' else ''} to promote)"

        # 11. Repository clone URL (ADO predefined variable)
        repo_clone_url = os.environ.get("BUILD_REPOSITORY_URI", "")

        # 12. Build result and render markdown
        result = PreCheckResult(
            version=ctx.version,
            instance=ctx.instance,
            source_branch=ctx.source_branch,
            target_branch=ctx.target_branch,
            source_env=ctx.source_env,
            target_env=ctx.target_env,
            source_sha=source_sha,
            target_sha=target_sha,
            commit_count=commit_count,
            since_ref=since_ref,
            last_author=last_author,
            last_date=last_date,
            last_message=last_message,
            changes_status=changes_status,
            tag_status=tag_status,
            target_tag_status=target_tag_status,
            version_status=version_status,
            commit_log=commit_log or "(no new commits)",
            diff_stat=diff_stat or "(unable to diff)",
            files_changed=files_changed or "(no changes)",
            repo_clone_url=repo_clone_url,
        )

        markdown = MarkdownReporter.render(result)

        # Write summary file (ADO artifact staging or temp)
        staging_dir = os.environ.get(
            "BUILD_ARTIFACTSTAGINGDIRECTORY",
            os.path.join(ctx.repo_dir, ".promote-artifacts"),
        )
        os.makedirs(staging_dir, exist_ok=True)
        summary_path = os.path.join(staging_dir, "Promotion Summary.md")

        with open(summary_path, "w", encoding="utf-8") as fh:
            fh.write(markdown)

        logger.upload_summary(summary_path)

        # 14. Build tags
        will_fail = (
            git.tag_exists(ctx.target_tag)
            or git.diff_quiet(diff_range)
        )
        logger.add_build_tag(f"status__{'fail' if will_fail else 'success'}")
        logger.add_build_tag(f"version__{ctx.version}")
        logger.add_build_tag(f"promotion__{ctx.source_env}-to-{ctx.target_env}")

        # Render output — Rich locally, plain markdown in pipeline
        if logger.is_pipeline():
            print(markdown)
        else:
            console.print()
            console.print(Panel(
                Markdown(markdown),
                title="[bold cyan]Promotion Summary[/bold cyan]",
                border_style="cyan",
            ))

        return 0
