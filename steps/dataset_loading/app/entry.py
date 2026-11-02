"""dataset-loading: pin the run's dataset to one commit.

The run picked `dataset` = `<dataset-repo>@<version>` (a dropdown on the submit
form). This step resolves it ONCE, with kaos-lib, to a lakeFS commit and
records it as the step output `dataset-info` (`dataset_commit`). Every later step takes
that output (`--dataset-info`) and reads exactly that commit, so a `latest` that moves
during the run never changes what the run trains on.

It downloads nothing: the data is read by the step that uses it (see hello_world).
"""

import argparse
import json
from pathlib import Path

import yaml
from kaos_lib import datasets

# The config sections this step reads (must exist in the config/ tree).
READS = ["dataset"]

OUTPUT_DIR = Path("/work/output")


def pin(dataset: str, client=None) -> dict:
    """Resolve `<dataset-repo>@<version>` to the record every later step receives."""
    ref = datasets.DatasetRef.parse(dataset)  # DatasetError names what is wrong and what is valid
    commit = datasets.resolve(ref, client)
    return {"dataset": str(ref), "dataset_repo": ref.repo, "dataset_version": ref.version,
            "dataset_commit": commit}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True,
                        help="Resolved params.yaml content (from compose-and-validate).")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params) or {}

    info = pin(cfg.get("dataset"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "dataset-info.json").write_text(json.dumps(info, separators=(",", ":")))
    print(f"[dataset-loading] {info['dataset']} -> commit {info['dataset_commit']}")


if __name__ == "__main__":
    main()
