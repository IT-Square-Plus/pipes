"""MetaConfig — read and write meta.yaml using PyYAML."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml

from shared.exceptions import MetaYamlError

if TYPE_CHECKING:
    from promote.services.git import GitService


class MetaConfig:
    """Read meta.yaml from a git branch or working directory, and update it."""

    FILENAME = "meta.yaml"

    @staticmethod
    def read_from_branch(branch: str, git: GitService) -> dict:
        """Read meta.yaml content from a remote branch via ``git show``.

        Returns the parsed YAML as a dict with at least ``version`` and ``instance``.
        """
        try:
            raw = git.show(f"origin/{branch}", MetaConfig.FILENAME)
        except Exception as exc:
            raise MetaYamlError(
                f"Cannot read {MetaConfig.FILENAME} from origin/{branch}: {exc}"
            ) from exc

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MetaYamlError(f"Failed to parse {MetaConfig.FILENAME}: {exc}") from exc

        if not isinstance(data, dict):
            raise MetaYamlError(f"{MetaConfig.FILENAME} is not a YAML mapping")

        for key in ("version", "instance"):
            if key not in data:
                raise MetaYamlError(f"Missing required key '{key}' in {MetaConfig.FILENAME}")

        # Ensure string types (YAML may parse bare numbers)
        data["version"] = str(data["version"])
        data["instance"] = str(data["instance"])

        return data

    @staticmethod
    def update_environment(repo_dir: str, target_env: str) -> None:
        """Update the ``environment`` field in meta.yaml inside the working directory."""
        path = os.path.join(repo_dir, MetaConfig.FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as exc:
            raise MetaYamlError(f"Cannot read {path}: {exc}") from exc

        data["environment"] = target_env

        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)
