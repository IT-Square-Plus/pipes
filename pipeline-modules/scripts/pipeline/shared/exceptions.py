"""Custom exceptions for the pipeline package."""


class PromoteError(Exception):
    """Base exception for all promotion errors."""


class GitError(PromoteError):
    """Raised when a git command fails."""

    def __init__(self, command: str, returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {command} failed (rc={returncode}): {stderr}")


class VersionRegressionError(PromoteError):
    """Raised when the current version is lower than the last promoted version."""

    def __init__(self, current: str, last: str, last_tag: str) -> None:
        self.current = current
        self.last = last
        self.last_tag = last_tag
        super().__init__(
            f"Version REGRESSION detected: {current} < {last} (last tag: {last_tag})"
        )


class MetaYamlError(PromoteError):
    """Raised when meta.yaml cannot be read or parsed."""


class AdoApiError(PromoteError):
    """Raised when an Azure DevOps REST API call fails."""

    def __init__(self, url: str, status_code: int, body: str) -> None:
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"ADO API error {status_code} for {url}: {body}")
