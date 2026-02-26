"""Base command — abstract interface for all promote sub-commands."""

from __future__ import annotations

from abc import ABC, abstractmethod

from promote.models.context import PromotionContext


class BaseCommand(ABC):
    """Abstract base for promote sub-commands."""

    def __init__(self, ctx: PromotionContext) -> None:
        self._ctx = ctx

    @abstractmethod
    def execute(self) -> int:
        """Run the command and return an exit code (0 = success)."""
