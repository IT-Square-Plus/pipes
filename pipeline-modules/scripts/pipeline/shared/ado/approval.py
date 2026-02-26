"""ApprovalService — CRUD for Azure DevOps approval checks on environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.ado.client import AdoClient

# Constant type ID for approval checks in Azure DevOps
APPROVAL_TYPE_ID = "8c6f20a7-a545-4486-9777-f762fafe0d4d"


class ApprovalService:
    """Manage approval checks on ADO pipeline environments."""

    def __init__(self, client: AdoClient) -> None:
        self._client = client

    def find_on_environment(self, env_id: int) -> int | None:
        """Return the approval check ID if one exists on the environment, or ``None``."""
        data = self._client.get(
            f"_apis/pipelines/checks/configurations?"
            f"resourceType=environment&resourceId={env_id}&$expand=settings",
            preview=True,
        )
        for check in data.get("value", []):
            if check.get("type", {}).get("id") == APPROVAL_TYPE_ID:
                return check["id"]
        return None

    def get_check_details(self, env_id: int) -> dict | None:
        """Return the full approval check object for the environment, or ``None``.

        The returned dict contains keys like ``id``, ``settings``
        (with ``approvers``, ``minRequiredApprovers``), etc.
        """
        data = self._client.get(
            f"_apis/pipelines/checks/configurations?"
            f"resourceType=environment&resourceId={env_id}&$expand=settings",
            preview=True,
        )
        for check in data.get("value", []):
            if check.get("type", {}).get("id") == APPROVAL_TYPE_ID:
                return check
        return None

    def create(
        self,
        env_id: int,
        env_name: str,
        approvers: list[dict],
        min_required: int = 1,
    ) -> int:
        """Create an approval check on the environment and return its ID."""
        body = {
            "type": {"id": APPROVAL_TYPE_ID, "name": "Approval"},
            "settings": {
                "approvers": approvers,
                "executionOrder": "anyOrder",
                "minRequiredApprovers": min_required,
                "instructions": f"Approve promotion to {env_name}",
                "blockedApprovers": [],
            },
            "timeout": 43200,
            "resource": {
                "type": "environment",
                "id": str(env_id),
                "name": env_name,
            },
        }
        data = self._client.post(
            "_apis/pipelines/checks/configurations", body, preview=True
        )
        return data["id"]

    def update(
        self,
        check_id: int,
        env_id: int,
        env_name: str,
        approvers: list[dict],
        min_required: int = 1,
    ) -> int:
        """Update an existing approval check and return its ID."""
        body = {
            "id": check_id,
            "type": {"id": APPROVAL_TYPE_ID, "name": "Approval"},
            "settings": {
                "approvers": approvers,
                "executionOrder": "anyOrder",
                "minRequiredApprovers": min_required,
                "instructions": f"Approve promotion to {env_name}",
                "blockedApprovers": [],
            },
            "timeout": 43200,
            "resource": {
                "type": "environment",
                "id": str(env_id),
                "name": env_name,
            },
        }
        data = self._client.patch(
            f"_apis/pipelines/checks/configurations/{check_id}", body, preview=True
        )
        return data["id"]

    def get_or_create(
        self,
        env_id: int,
        env_name: str,
        approvers: list[dict],
        min_required: int = 1,
    ) -> tuple[int, bool]:
        """Return ``(check_id, created)``."""
        existing = self.find_on_environment(env_id)
        if existing is not None:
            return existing, False
        return self.create(env_id, env_name, approvers, min_required), True
