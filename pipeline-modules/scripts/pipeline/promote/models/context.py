"""Promotion context — central dataclass holding all promotion parameters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromotionContext:
    """Holds all parameters for a single promotion run.

    Basic fields come from CLI args; version/instance are enriched
    from meta.yaml at runtime; tags are computed from those values.
    """

    source_branch: str
    target_branch: str
    source_env: str
    target_env: str
    repo_dir: str

    # Enriched from meta.yaml
    version: str = ""
    instance: str = ""

    # Computed tags: {version}-{env}{instance}
    source_tag: str = field(default="", init=False)
    target_tag: str = field(default="", init=False)

    def compute_tags(self) -> None:
        """Compute source and target tags from version, env, and instance."""
        self.source_tag = f"{self.version}-{self.source_env}{self.instance}"
        self.target_tag = f"{self.version}-{self.target_env}{self.instance}"
