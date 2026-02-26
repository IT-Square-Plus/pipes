"""VersionService — semantic version comparison using ``packaging``."""

from __future__ import annotations

from packaging.version import Version, InvalidVersion


class VersionService:
    """Compare versions to detect regressions."""

    @staticmethod
    def check_regression(current: str, last_tag: str, last_version: str) -> str | None:
        """Check if *current* version is a regression compared to *last_version*.

        Returns:
            ``None`` if no issue, or a human-readable status string.
        """
        try:
            v_current = Version(current)
            v_last = Version(last_version)
        except InvalidVersion:
            return None

        if v_current == v_last:
            return (
                f"\u26a0\ufe0f Version {current} is the same as last promoted ({last_tag})"
            )
        if v_current < v_last:
            return (
                f"\u274c Version REGRESSION detected: {current} < {last_version} "
                f"(last tag: {last_tag})"
            )
        return None

    @staticmethod
    def is_regression(current: str, last_version: str) -> bool:
        """Return True if *current* is strictly lower than *last_version*."""
        try:
            return Version(current) < Version(last_version)
        except InvalidVersion:
            return False
