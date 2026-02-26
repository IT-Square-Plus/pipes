"""EnvironmentService — CRUD for Azure DevOps environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.ado.client import AdoClient


class EnvironmentService:
    """Create and query ADO pipeline environments."""

    def __init__(self, client: AdoClient) -> None:
        self._client = client

    def get_by_name(self, name: str) -> int | None:
        """Return the environment ID if it exists, or ``None``."""
        data = self._client.get(
            "_apis/distributedtask/environments", preview=True
        )
        for env in data.get("value", []):
            if env.get("name") == name:
                return env["id"]
        return None

    def create(self, name: str, description: str = "") -> int:
        """Create an environment and return its ID."""
        if not description:
            description = f"Promotion target environment: {name}"
        data = self._client.post(
            "_apis/distributedtask/environments",
            {"name": name, "description": description},
            preview=True,
        )
        return data["id"]

    def get_or_create(self, name: str) -> tuple[int, bool]:
        """Return ``(env_id, created)``."""
        existing = self.get_by_name(name)
        if existing is not None:
            return existing, False
        return self.create(name), True
