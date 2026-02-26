"""TagService — tag naming conventions and lookup."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promote.services.git import GitService


class TagService:
    """Build, find, and parse promotion tags."""

    @staticmethod
    def build_tag(version: str, env: str, instance: str) -> str:
        """Build a tag name following the ``{version}-{env}{instance}`` convention."""
        return f"{version}-{env}{instance}"

    @staticmethod
    def find_last_promotion_tag(
        git: GitService,
        branch: str,
        env: str,
        instance: str,
    ) -> str | None:
        """Find the most recent promotion tag on *branch* matching the env/instance pattern.

        Returns the tag name or ``None`` if not found.
        """
        pattern = re.compile(rf"-{re.escape(env)}{re.escape(instance)}$")
        tags = git.tags_merged(f"origin/{branch}")
        for tag in tags:
            if pattern.search(tag):
                return tag
        return None

    @staticmethod
    def extract_version_from_tag(tag: str) -> str:
        """Strip the ``-{env}{instance}`` suffix from a tag to get the version part."""
        return re.sub(r"-[a-z]+\d*$", "", tag)
