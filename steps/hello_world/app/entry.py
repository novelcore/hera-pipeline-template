"""hello-world: the example step. Reads the pinned dataset and writes a result.

Every step is a small container that receives the resolved params.yaml (the composed
config tree) on --params, and the outputs of the steps it needs (here `--dataset-info`
from dataset-loading). This one:

  1. reads the dataset at the commit dataset-loading pinned, through the kubecore
     package (`get_format(...).consumer`): a local `data.yaml` Ultralytics could train
     on. On MeluXina the platform stages the commit and the package uses that copy;
  2. writes a small result to the app's own outputs repository `outputs-<app>` with
     `kubecore.outputs.write_run` (one commit per step per run).

Replace the body with your own logic, and add your runtime dependencies to the Dockerfile.
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

import yaml
from kubecore import datasets, outputs
from kubecore.formats import get_format

# The config sections this step reads (must exist in the config/ tree).
READS = ["experiment", "dataset"]


def pinned_client(commit: str, client=None):
    """A lakeFS client whose refs all resolve to `commit`.

    The consumer resolves the ref it is given; passing it this client makes it read the
    commit dataset-loading pinned even when the choice was `latest`. (The package has no
    `commit=` argument yet; drop this when it does.)
    """
    from kubecore.lakefs import LakeFS
    c = client or LakeFS.connect()
    c.branch_commit = lambda repo, branch: commit
    c.tag_commit = lambda repo, tag: commit
    return c


def read_dataset(info: dict, client=None) -> Path:
    """Local data.yaml of the pinned dataset commit (downloaded once, or the staged copy)."""
    commit = info.get("dataset_commit") or ""
    if not commit:
        raise SystemExit("[hello-world] --dataset-info carries no dataset_commit: run dataset-loading first.")
    ref = datasets.DatasetRef.parse(info["dataset"])
    return get_format("ultralytics").consumer.materialize(ref, None, pinned_client(commit, client))


def write_result(cfg: dict, info: dict, data_yaml: Path, client=None) -> str:
    """Write the result to outputs-<app>/checkpoints/<experiment>/<run>/ and return the commit."""
    data = yaml.safe_load(data_yaml.read_text()) or {}
    result = {"dataset": info["dataset"], "dataset_commit": info["dataset_commit"],
              "classes": data.get("names"), "experiment": cfg["experiment"]["name"]}
    # CHECKPOINT_BUCKET is `outputs-<app>`, injected by the platform.
    app = os.environ.get("CHECKPOINT_BUCKET") or ((cfg.get("platform") or {}).get("checkpoints") or {}).get("bucket")
    run = os.environ.get("KUBECORE_RUN_ID") or "local"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "hello.json").write_text(json.dumps(result, indent=2))
        return outputs.write_run(app, cfg["experiment"]["name"], run, tmp, client=client)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True,
                        help="Resolved params.yaml content (from compose-and-validate).")
    parser.add_argument("--dataset-info", default="{}",
                        help="dataset-loading's {dataset, dataset_commit}: the pinned dataset.")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params) or {}
    info = json.loads(args.dataset_info or "{}")

    data_yaml = read_dataset(info)
    print(f"[hello-world] {info['dataset']} @ {info['dataset_commit']} -> {data_yaml}")
    commit = write_result(cfg, info, data_yaml)
    print(f"[hello-world] result committed to outputs: {commit}")


if __name__ == "__main__":
    main()
