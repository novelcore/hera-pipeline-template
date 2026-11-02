"""hello-world: the example step. Reads the pinned dataset and writes a result.

Every step is a small container that receives the resolved params.yaml (the composed
config tree) on --params, and the outputs of the steps it needs (here `--dataset-info`
from dataset-loading). This one:

  1. reads the dataset at the commit dataset-loading pinned, through the kubecore
     package (`datasets.materialize`). The package picks the dataset's format from its
     `kaos.template` label (an unlabelled repository is read as plain files) and returns
     the local entry point. On MeluXina the platform stages the commit and the package
     uses that copy;
  2. writes a small result to the app's own outputs repository `outputs-<app>` with the run
     writer `kubecore.outputs.run` (one merge commit on main per step per run).

Replace the body with your own logic, and add your runtime dependencies to the Dockerfile.
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

import yaml
from kubecore import datasets, outputs

# The config sections this step reads (must exist in the config/ tree).
READS = ["experiment", "dataset"]


def read_dataset(info: dict, client=None) -> Path:
    """Local entry point of the pinned dataset commit (downloaded once, or the staged copy).

    For a labelled dataset such as a yolo one it is the `data.yaml`; for a plain
    repository it is the folder holding the files.
    """
    commit = info.get("dataset_commit") or ""
    if not commit:
        raise SystemExit("[hello-world] --dataset-info carries no dataset_commit: run dataset-loading first.")
    ref = datasets.DatasetRef.parse(info["dataset"]).with_commit(commit)  # read the pinned commit, never a moving ref
    return datasets.materialize(ref, client=client)  # the format comes from the repository's label


def describe(entry: Path) -> dict:
    """What a person wants to see about the data: its classes (a YAML entry point) or its file count."""
    if entry.is_file():
        return {"classes": (yaml.safe_load(entry.read_text()) or {}).get("names")}
    return {"files": sum(1 for p in entry.rglob("*") if p.is_file() and not p.name.startswith("."))}


def write_result(cfg: dict, info: dict, entry: Path, client=None) -> str:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True,
                        help="Resolved params.yaml content (from compose-and-validate).")
    parser.add_argument("--dataset-info", default="{}",
                        help="dataset-loading's {dataset, dataset_commit}: the pinned dataset.")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params) or {}
    info = json.loads(args.dataset_info or "{}")

    entry = read_dataset(info)
    print(f"[hello-world] {info['dataset']} @ {info['dataset_commit']} -> {entry}")
    commit = write_result(cfg, info, entry)
    print(f"[hello-world] result committed to outputs: {commit}")


if __name__ == "__main__":
    main()
