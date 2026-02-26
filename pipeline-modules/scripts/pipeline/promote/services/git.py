"""GitService — thin subprocess wrapper around git CLI."""

from __future__ import annotations

import subprocess

from shared.ado import logger
from shared.exceptions import GitError


class GitService:
    """Execute git commands in a given repository directory."""

    def __init__(self, repo_dir: str) -> None:
        self._repo_dir = repo_dir

    # ── Core runner ──

    def run(self, *args: str, check: bool = True) -> str:
        """Run a git command and return stripped stdout.

        Raises ``GitError`` on non-zero exit when *check* is True.
        """
        cmd = ["git", *args]
        logger.info(f"git {' '.join(args)}")
        result = subprocess.run(
            cmd,
            cwd=self._repo_dir,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(
                command=" ".join(args),
                returncode=result.returncode,
                stderr=result.stderr.strip(),
            )
        return result.stdout.strip()

    # ── Convenience methods (1:1 with git commands) ──

    def fetch_tags(self) -> str:
        return self.run("fetch", "origin", "--tags")

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", ref)

    def show(self, ref: str, path: str) -> str:
        return self.run("show", f"{ref}:{path}")

    def checkout(self, ref: str) -> str:
        return self.run("checkout", ref)

    def checkout_file(self, ref: str, path: str) -> str:
        return self.run("checkout", ref, "--", path)

    def pull(self, remote: str, branch: str) -> str:
        return self.run("pull", remote, branch)

    def merge_squash(self, ref: str) -> tuple[bool, str]:
        """Attempt a squash merge. Returns (success, output)."""
        try:
            output = self.run("merge", "--squash", ref)
            return True, output
        except GitError:
            return False, ""

    def checkout_theirs(self, *paths: str) -> str:
        return self.run("checkout", "--theirs", "--", *paths)

    def diff_name_only_unmerged(self) -> list[str]:
        output = self.run("diff", "--name-only", "--diff-filter=U", check=False)
        return [f for f in output.splitlines() if f]

    def add(self, *paths: str) -> str:
        return self.run("add", *paths)

    def add_all(self) -> str:
        return self.run("add", "-A")

    def commit(self, message: str) -> str:
        return self.run("commit", "-m", message)

    def tag(self, name: str) -> str:
        return self.run("tag", name)

    def tag_exists(self, name: str) -> bool:
        try:
            self.run("rev-parse", f"refs/tags/{name}")
            return True
        except GitError:
            return False

    def push(self, remote: str, ref: str) -> str:
        return self.run("push", remote, ref)

    def push_tags(self, remote: str = "origin") -> str:
        return self.run("push", remote, "--tags")

    def config(self, key: str, value: str) -> str:
        return self.run("config", key, value)

    def log(self, fmt: str, ref_range: str, *, no_merges: bool = True, max_count: int | None = None) -> str:
        args = ["log", f"--format={fmt}"]
        if no_merges:
            args.append("--no-merges")
        if max_count is not None:
            args.append(f"--max-count={max_count}")
        args.append(ref_range)
        return self.run(*args, check=False)

    def rev_list_count(self, ref_range: str, *, no_merges: bool = True) -> str:
        args = ["rev-list", "--count"]
        if no_merges:
            args.append("--no-merges")
        args.append(ref_range)
        return self.run(*args, check=False)

    def diff_stat(self, ref_range: str) -> str:
        return self.run("diff", "--stat", ref_range, check=False)

    def diff_shortstat(self, ref_range: str) -> str:
        return self.run("diff", "--shortstat", ref_range, check=False)

    def diff_name_only(self, ref_range: str) -> str:
        return self.run("diff", "--name-only", ref_range, check=False)

    def diff_quiet(self, ref_range: str) -> bool:
        """Return True if there are no differences."""
        try:
            self.run("diff", "--quiet", ref_range)
            return True
        except GitError:
            return False

    def diff_cached_quiet(self) -> bool:
        """Return True if the staging area has no changes."""
        try:
            self.run("diff", "--cached", "--quiet")
            return True
        except GitError:
            return False

    def merge_base(self, ref1: str, ref2: str) -> str:
        return self.run("merge-base", ref1, ref2, check=False)

    def tags_merged(self, ref: str, sort: str = "-version:refname") -> list[str]:
        """List tags merged into *ref*, sorted by version descending."""
        output = self.run("tag", f"--sort={sort}", "--merged", ref, check=False)
        return [t for t in output.splitlines() if t]

    def reset_head_quiet(self) -> str:
        return self.run("reset", "HEAD", "--quiet", check=False)

    def remote_url(self) -> str:
        return self.run("config", "--get", "remote.origin.url")
