"""hello-world: the example step. Reads the run's dataset and writes a result.

Every step is a small container that receives the resolved params.yaml (the composed
config tree) on --params, and the outputs of the steps it needs (this one needs none). This one:

  1. reads the run's dataset through the kaos-lib
     package (`datasets.materialize`). The platform pins every dataset of a run to one commit
     once and gives each step that lock, so the package reads that commit even when `latest` has
     moved on. The package picks the dataset's format from its
     `kaos.template` label (an unlabelled repository is read as plain files) and returns
     the local entry point. On HPC the platform stages the commit and the package
     uses that copy. A dataset with no files yet (a new project's `dataset-default`) is
     reported, not an error, so the first run of a new app succeeds;
  2. writes a small result to the app's own outputs repository `outputs-<app>` with the run
     writer `kaos_lib.outputs.run` (one merge commit on main per step per run).

Replace the body with your own logic, and add your runtime dependencies to the Dockerfile.
"""

import argparse
import json
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

import yaml
from kaos_lib import datasets, outputs
try:
    from kaos_lib.errors import EmptyDataset
except ImportError:  # kaos-lib before 0.4.0rc3 (an app pinned to it): an empty dataset still fails the step
    EmptyDataset = ()

# The config sections this step reads (must exist in the config/ tree).
READS = ["experiment", "dataset"]


def read_dataset(ref: "datasets.DatasetRef", client=None) -> Path:
    """Local entry point of the run's dataset (downloaded once, or the staged copy).

    For a labelled dataset such as a yolo one it is the `data.yaml`; for a plain
    repository it is the folder holding the files. Read at the commit the run's data lock gives `ref`.
    """
    return datasets.materialize(ref, client=client)  # the format comes from the repository's label


def describe(entry: Optional[Path]) -> dict:
    """What a person wants to see about the data: its classes (a YAML entry point) or its file count."""
    if entry is None:  # the dataset holds no files yet
        return {"files": 0}
    if entry.is_file():
        return {"classes": (yaml.safe_load(entry.read_text()) or {}).get("names")}
    return {"files": sum(1 for p in entry.rglob("*") if p.is_file() and not p.name.startswith("."))}


def write_result(cfg: dict, info: dict, entry: Optional[Path], client=None) -> str:
    """Write the result to outputs-<app>/checkpoints/<experiment>/<run>/ and return the commit."""
    result = {"dataset": info["dataset"], "dataset_commit": info["dataset_commit"],
              **describe(entry), "experiment": cfg["experiment"]["name"]}
    # CHECKPOINT_BUCKET is `outputs-<app>`, injected by the platform.
    app = os.environ.get("CHECKPOINT_BUCKET") or ((cfg.get("platform") or {}).get("checkpoints") or {}).get("bucket")
    run = os.environ.get("KUBECORE_RUN_ID") or "local"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "hello.json").write_text(json.dumps(result, indent=2))
        # The run writer saves on the branch run-<run>-checkpoints (durable, reused on a retry) and
        # finish() merges it into main: one commit on main per step per run, then the branch is gone.
        with outputs.run(app, cfg["experiment"]["name"], run, client=client) as r:
            r.save(tmp)
            return r.finish({"dataset_ref": info["dataset"], "dataset_commit": info["dataset_commit"]})


def kaos_lib_version() -> str:
    """The installed kaos-lib version (distribution `kaos-lib`, or `kubecore` before its first release)."""
    for dist in ("kaos-lib", "kubecore"):
        try:
            return version(dist)
        except PackageNotFoundError:
            pass
    return "unknown"


def main(client=None) -> None:
    print(f"kaos-lib {kaos_lib_version()}", flush=True)  # the package this image runs
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True,
                        help="Resolved params.yaml content (composed by the platform).")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params) or {}
    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref, client)  # KAOS_LIB_LOCK (set by the platform) supplies the commit
    ref = ref.with_commit(commit)
    info = {"dataset": cfg["dataset"], "dataset_commit": commit}

    try:
        entry = read_dataset(ref, client)
        print(f"[hello-world] {info['dataset']} @ {info['dataset_commit']} -> {entry}")
    except EmptyDataset:
        entry = None
        print(f"[hello-world] {info['dataset']} @ {info['dataset_commit']} holds no files yet. Add yours with "
              f"`kaosctl dataset push <folder> <dataset>` (docs/first-run.md), then run again.")
    commit = write_result(cfg, info, entry, client)
    print(f"[hello-world] result committed to outputs: {commit}")


if __name__ == "__main__":
    main()
