"""AdoClient — lightweight HTTP client for Azure DevOps REST API."""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from typing import Any

from shared.exceptions import AdoApiError


class AdoClient:
    """HTTP client for Azure DevOps REST API using ``urllib.request``."""

    API_VERSION = "7.1"

    def __init__(self, org: str, project: str, pat: str) -> None:
        self._org = org
        self._project = project
        self._base_url = f"https://dev.azure.com/{org}/{project}"
        self._org_url = f"https://dev.azure.com/{org}"
        self._auth_header = self._build_auth_header(pat)

    @staticmethod
    def _build_auth_header(pat: str) -> str:
        token = base64.b64encode(f":{pat}".encode()).decode()
        return f"Basic {token}"

    def _request(
        self,
        method: str,
        url: str,
        body: dict | None = None,
    ) -> dict | list | None:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth_header,
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode() if exc.fp else ""
            raise AdoApiError(url, exc.code, body_text) from exc

    def get(self, path: str, *, preview: bool = False) -> Any:
        """Send a GET request. *path* is relative to the project base URL."""
        version = f"{self.API_VERSION}-preview.1" if preview else self.API_VERSION
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}api-version={version}"
        return self._request("GET", url)

    def post(self, path: str, body: dict, *, preview: bool = False) -> Any:
        """Send a POST request."""
        version = f"{self.API_VERSION}-preview.1" if preview else self.API_VERSION
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}api-version={version}"
        return self._request("POST", url, body)

    def put(self, path: str, body: dict, *, preview: bool = False) -> Any:
        """Send a PUT request."""
        version = f"{self.API_VERSION}-preview.1" if preview else self.API_VERSION
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}api-version={version}"
        return self._request("PUT", url, body)

    def patch(self, path: str, body: dict, *, preview: bool = False) -> Any:
        """Send a PATCH request."""
        version = f"{self.API_VERSION}-preview.1" if preview else self.API_VERSION
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}api-version={version}"
        return self._request("PATCH", url, body)

    def get_org(self, path: str) -> Any:
        """Send a GET request at org level (no project in URL)."""
        separator = "&" if "?" in path else "?"
        url = f"{self._org_url}/{path}{separator}api-version={self.API_VERSION}"
        return self._request("GET", url)

    def get_vsaex(self, path: str) -> Any:
        """Send a GET request to vsaex.dev.azure.com (User Entitlements API)."""
        base = f"https://vsaex.dev.azure.com/{self._org}"
        separator = "&" if "?" in path else "?"
        url = f"{base}/{path}{separator}api-version={self.API_VERSION}-preview.4"
        return self._request("GET", url)

    def validate_pat(self) -> bool:
        """Validate the PAT by querying the project endpoint."""
        try:
            self.get_org(f"_apis/projects/{self._project}")
            return True
        except AdoApiError:
            return False

    @property
    def org(self) -> str:
        return self._org

    @property
    def project(self) -> str:
        return self._project

    @property
    def base_url(self) -> str:
        return self._base_url
