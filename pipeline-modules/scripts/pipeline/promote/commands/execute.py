"""ExecuteCommand — perform the actual promotion (merge, tag, push)."""

from __future__ import annotations

import os

from rich.panel import Panel

from shared.ado import logger
from promote.commands.base import BaseCommand
from shared.console import console
from promote.models.meta import MetaConfig
from promote.services.git import GitService
from promote.services.tag import TagService
from promote.services.version import VersionService


class ExecuteCommand(BaseCommand):
    """Squash-merge source into target, tag, and push."""

    def execute(self) -> int:
        ctx = self._ctx
        git = GitService(ctx.repo_dir)

        # 1. Set git identity
        git.config("user.email", "azure-pipeline@metlife.com")
        git.config("user.name", "Azure Pipeline")

        # 2. Fetch all branches and tags
        git.fetch_tags()

        # 3. Read meta.yaml from source branch
        meta = MetaConfig.read_from_branch(ctx.source_branch, git)
        ctx.version = meta["version"]
        ctx.instance = meta["instance"]
        ctx.compute_tags()

        logger.set_variable("VERSION", ctx.version)
        logger.info(f"Version from meta.yaml: {ctx.version} (instance: {ctx.instance})")

        # 4. Version regression check
        last_source_tag = TagService.find_last_promotion_tag(
            git, ctx.source_branch, ctx.source_env, ctx.instance
        )
        if last_source_tag:
            last_version = TagService.extract_version_from_tag(last_source_tag)
            if VersionService.is_regression(ctx.version, last_version):
                logger.error(
                    f"Version REGRESSION detected: {ctx.version} < {last_version} "
                    f"(last tag: {last_source_tag}). Aborting!"
                )
                return 1

        # 5. Tag source commit (idempotent)
        if git.tag_exists(ctx.source_tag):
            logger.warning(
                f"Source tag '{ctx.source_tag}' already exists \u2014 "
                "skipping source tagging (idempotent re-run)"
            )
        else:
            git.checkout(f"origin/{ctx.source_branch}")
            git.tag(ctx.source_tag)
            logger.success(f"Tagged source commit as '{ctx.source_tag}'")

        # 6. Checkout target branch
        git.checkout(ctx.target_branch)
        git.pull("origin", ctx.target_branch)

        # 7. Squash merge
        logger.info(
            f"Squash merge {ctx.source_branch} \u2192 {ctx.target_branch}..."
        )
        success, _ = git.merge_squash(f"origin/{ctx.source_branch}")
        if not success:
            logger.warning(
                "Merge conflicts detected \u2014 auto-resolving with source branch"
            )
            conflicted = git.diff_name_only_unmerged()
            if conflicted:
                logger.info("Conflicted files: " + ", ".join(conflicted))
                git.checkout_theirs(*conflicted)
                git.add(*conflicted)

        # 8. Update environment in meta.yaml
        MetaConfig.update_environment(ctx.repo_dir, ctx.target_env)
        git.add_all()

        # 9. Check for actual changes
        if git.diff_cached_quiet():
            logger.warning(
                "No changes to promote \u2014 source and target are identical. "
                "Skipping commit and push."
            )
            logger.set_variable("HAS_CHANGES", "false")
            git.reset_head_quiet()
            squash_msg = os.path.join(ctx.repo_dir, ".git", "SQUASH_MSG")
            if os.path.exists(squash_msg):
                os.remove(squash_msg)
            return 0

        logger.set_variable("HAS_CHANGES", "true")

        # 10. Commit
        git.commit(f"Promote {ctx.version} from {ctx.source_env} to {ctx.target_env}")

        # 11. Tag target commit
        if git.tag_exists(ctx.target_tag):
            logger.error(
                f"Target tag '{ctx.target_tag}' already exists \u2014 "
                "aborting to prevent duplicate promotion!"
            )
            return 1
        git.tag(ctx.target_tag)
        logger.success(f"Tagged target commit as '{ctx.target_tag}'")

        # 12. Push
        git.push("origin", ctx.target_branch)
        git.push_tags()

        # Success summary
        if not logger.is_pipeline():
            console.print()
            console.print(Panel(
                f"[bold green]Promoted {ctx.version}[/bold green]\n"
                f"{ctx.source_env} ({ctx.source_branch}) \u2192 "
                f"{ctx.target_env} ({ctx.target_branch})\n"
                f"Tags: {ctx.source_tag}, {ctx.target_tag}",
                title="[bold green]Promotion Complete[/bold green]",
                border_style="green",
            ))
        else:
            logger.success(
                f"Promoted {ctx.version} from {ctx.source_env} to {ctx.target_env}"
            )

        return 0
