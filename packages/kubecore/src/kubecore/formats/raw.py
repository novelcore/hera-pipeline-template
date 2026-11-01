"""The ``raw`` format: any lakeFS repository, no layout assumed.

Consumer: downloads the whole tree (or a ``prefix``) at the pinned commit and returns the folder.
Creator: no skeleton, validation always passes, publish uploads the folder as is.
"""
from __future__ import annotations

import pathlib
from typing import Optional

from .. import datasets
from ..errors import DatasetError
from ..lakefs import LakeFS
from . import Format, ValidationReport, local, register

NAME = "raw"


class RawCreator:
    """Uploads folders unchanged; there is nothing to scaffold or check."""

    name = NAME

    def skeleton(self, **_ignored) -> dict:
        return {}

    def validate(self, local_dir) -> ValidationReport:
        return ValidationReport([]) if pathlib.Path(local_dir).is_dir() \
            else ValidationReport([f"{local_dir} is not a directory"])

    def publish(self, local_dir, repo: str, message: str, via_pull_request: bool = True,
                description: str = "", validate_first: bool = True, metadata: Optional[dict] = None,
                client: Optional[LakeFS] = None) -> datasets.PublishResult:
        """Upload ``local_dir`` to ``repo`` through a draft branch and a pull request (repo created if missing)."""
        labels = {datasets.LABEL_KIND: "dataset"}
        if description:
            labels[datasets.LABEL_DESCRIPTION] = description
        return datasets.publish_tree(local_dir, repo, message, via_pull_request, labels, client, metadata)


class RawConsumer:
    """Makes any version of any repository available as a local folder."""

    name = NAME

    def materialize(self, ref: datasets.DatasetRef, dest=None, client: Optional[LakeFS] = None,
                    commit: Optional[str] = None, prefix: Optional[str] = None) -> pathlib.Path:
        """Local folder holding the whole tree (or only ``prefix``, with the prefix removed) of ``ref``.

        Cached by (repo, commit, prefix) in ``dest`` (default: the cache); a second call is free. A staged
        copy (KUBECORE_STAGED_DIR holding the commit) is used in place.
        """
        commit = datasets.resolve(ref, client, commit)
        pre = (prefix.strip("/") + "/") if prefix and prefix.strip("/") else None
        staged = local.staged_dir(commit)
        if staged and (not pre or (staged / pre).is_dir()):
            return staged / pre if pre else staged
        target = pathlib.Path(dest) if dest else local.cache_dir(ref.repo, commit, pre)
        if local.marker_matches(target, ref.repo, commit, pre):
            return target
        local.fetch(client, ref.repo, commit, [pre or ""], target, pre, strip=pre or "",
                    empty_message=f"{ref} holds no files" + (f" under {pre}" if pre else "") + ".")
        return target


register(Format(NAME, RawCreator(), RawConsumer()))
