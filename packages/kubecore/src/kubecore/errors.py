"""Error types. Everything the CLI shows as a one-line message derives from KubecoreError."""
from __future__ import annotations


class KubecoreError(Exception):
    """A user-facing failure: the message says what happened and what to do next."""


class ConfigError(KubecoreError):
    """A required setting (lakeFS URL, ...) could not be determined."""


class AuthError(KubecoreError):
    """No usable credential, or lakeFS rejected the one we carry."""


class LakeFSError(KubecoreError):
    """A lakeFS API call failed. ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class NotFoundError(LakeFSError):
    """The repository, ref, tag or object does not exist."""


class DatasetError(KubecoreError):
    """A dataset reference or operation is invalid (bad ref, nothing to release, ...)."""


class ValidationFailed(KubecoreError):
    """A local dataset failed format validation; ``errors`` holds every problem found."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"dataset failed validation ({len(errors)} problem(s))")
