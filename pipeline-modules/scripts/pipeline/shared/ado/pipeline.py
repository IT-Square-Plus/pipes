"""PipelineService — CRUD for Azure DevOps pipeline definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.ado.client import AdoClient


class PipelineService:
    """Create and query ADO pipeline definitions."""

    def __init__(self, client: AdoClient) -> None:
        self._client = client

    def find_by_name_and_folder(self, name: str, folder: str) -> int | None:
        """Return the pipeline ID if it exists (case-insensitive), or ``None``."""
        data = self._client.get("_apis/pipelines", preview=True)
        name_lower = name.lower()
        folder_lower = folder.lower()
        for pipeline in data.get("value", []):
            if (
                pipeline.get("name", "").lower() == name_lower
                and pipeline.get("folder", "").lower() == folder_lower
            ):
                return pipeline["id"]
        return None

    def create(
        self,
        name: str,
        folder: str,
        yaml_path: str,
        repo_id: str,
        repo_name: str,
        default_branch: str = "refs/heads/main",
    ) -> int:
        """Create a pipeline definition and return its ID."""
        body = {
            "name": name,
            "folder": folder,
            "configuration": {
                "type": "yaml",
                "path": f"/{yaml_path}",
                "repository": {
                    "id": repo_id,
                    "name": repo_name,
                    "type": "azureReposGit",
                    "defaultBranch": default_branch,
                },
            },
        }
        data = self._client.post("_apis/pipelines", body, preview=True)
        return data["id"]

    def update(
        self,
        pipeline_id: int,
        yaml_path: str,
        repo_id: str,
        repo_name: str,
        default_branch: str,
    ) -> None:
        """Update an existing pipeline definition (name, YAML path, default branch)."""
        # Use Build Definitions API for full update support
        definition = self._client.get(f"_apis/build/definitions/{pipeline_id}")
        definition["process"]["yamlFilename"] = f"/{yaml_path}"
        definition["repository"]["defaultBranch"] = default_branch
        self._client.put(f"_apis/build/definitions/{pipeline_id}", definition)

    def get_or_create(
        self,
        name: str,
        folder: str,
        yaml_path: str,
        repo_id: str,
        repo_name: str,
        default_branch: str = "refs/heads/main",
    ) -> tuple[int, bool]:
        """Return ``(pipeline_id, created)``."""
        existing = self.find_by_name_and_folder(name, folder)
        if existing is not None:
            return existing, False
        return self.create(name, folder, yaml_path, repo_id, repo_name, default_branch), True
