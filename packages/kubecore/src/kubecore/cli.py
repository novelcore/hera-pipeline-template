"""The ``kubecore`` command line.

    kubecore login
    kubecore dataset create|list|versions|release|push|pull|validate

User errors print one ``ERROR:`` line (exit 1; validation problems exit 2), never a
traceback. Every successful command prints the next useful step and a link.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

import requests

from . import __version__, credentials, datasets
from .config import resolve_endpoint
from .errors import KubecoreError, ValidationFailed
from .formats import format_names, get_format
from .lakefs import LakeFS

EXIT_USER_ERROR, EXIT_INVALID_DATASET = 1, 2


def _connect(args) -> LakeFS:
    """Build the lakeFS client from --url / env / app config and the credential chain."""
    return LakeFS.connect(getattr(args, "url", None))


def _repo_url(c: LakeFS, repo: str, tail: str = "objects") -> str:
    return f"{c.base_url}/repositories/{repo}/{tail}"


def _print_errors(errors: list) -> None:
    from .formats import ValidationReport
    print(ValidationReport(errors).format(), file=sys.stderr)


# ------------------------------------------------------------------ commands
def cmd_login(args) -> int:
    url = resolve_endpoint(args.url)
    credentials.browser_login(url)
    print("Next: kubecore dataset list")
    return 0


def _repo(c: LakeFS, name: str) -> str:
    """An existing repository by its exact name, else the ``dataset-<name>`` shorthand."""
    return name if c.repository(name) else datasets.dataset_repo(name)


def cmd_create(args) -> int:
    c = _connect(args)
    classes = [x.strip() for x in (args.classes or "").split(",") if x.strip()]
    repo = datasets.create_dataset(args.name, args.template, args.description or "", c,
                                   classes=classes, title=args.name)
    if args.template == datasets.NO_TEMPLATE:
        print(f"Created {repo}: empty, no template (labelled kaos.kind=dataset).")
        print(f"  Open it:  {_repo_url(c, repo)}")
        print("kaos-lake lists it as a dataset once its first commit lands. Next: push your files")
        print(f"  kubecore dataset push ./my-files {repo} -m \"first files\"")
        return 0
    print(f"Created {repo} ({get_format(args.template).name}).")
    print(f"  Open it:  {_repo_url(c, repo)}")
    print("Next: get a local copy, add your images and labels, then push (opens a pull request):")
    print(f"  kubecore dataset pull {repo}@latest ./{repo}")
    print(f"  kubecore dataset push ./{repo} {repo} -m \"add images\"")
    return 0


def cmd_list(args) -> int:
    rows = datasets.list_datasets(_connect(args))
    if not rows:
        print("No datasets yet. Create one with: kubecore dataset create <name> --classes a,b,c")
        return 0
    width = max(len(r.repo) for r in rows)
    for r in rows:
        flags = "  [default]" if r.default else ""
        print(f"{r.repo:<{width}}  {r.template or '-':<12}  {r.description}{flags}")
    print(f"Next: kubecore dataset versions {rows[0].repo}")
    return 0


def cmd_versions(args) -> int:
    c = _connect(args)
    repo = _repo(c, args.repo)
    found = datasets.versions(repo, c)
    print(f"{repo}: {', '.join(found) if found else 'no versions yet'} (and {datasets.LATEST}, the head of main)")
    if found:
        print(f"Pick one in the pipeline:  dataset = {repo}@{found[-1]}")
    else:
        print(f"Next: kubecore dataset release {repo}")
    return 0


def cmd_release(args) -> int:
    c = _connect(args)
    repo = _repo(c, args.repo)
    version = datasets.release(repo, c)
    print(f"Released {repo} {version}.")
    print(f"  Open it:  {_repo_url(c, repo, f'objects?ref={version}')}")
    print(f"Pick it in the pipeline:  dataset = {repo}@{version}")
    return 0


def cmd_push(args) -> int:
    c = _connect(args)
    repo = _repo(c, args.repo)
    fmt_name = args.format or datasets.format_of(repo, c)   # no template label: raw, validates nothing
    if args.no_validate:
        print("WARNING: --no-validate: the dataset was not validated; training may fail on bad labels.",
              file=sys.stderr)
    result = get_format(fmt_name).creator.publish(
        args.dir, repo, args.message, description=args.description or "",
        validate_first=not args.no_validate, client=c)
    if result.created:
        print(f"Created {repo}.")
    print(f"Uploaded to draft branch {result.branch} and opened a pull request into main.")
    print(f"  Review and merge it:  {result.pull_url}")
    print(f"Next: after merging, run  kubecore dataset release {repo}")
    return 0


def cmd_pull(args) -> int:
    c = _connect(args)
    ref = datasets.DatasetRef.parse(args.ref)
    path = datasets.materialize(ref, args.dest, args.format, c, prefix=args.prefix)
    print(f"Ready: {path}")
    if path.is_dir():
        print(f"Next: your files are in {path}; read them from there in your code.")
    else:
        print(f"Next: train with it, e.g.  YOLO('yolo11n.pt').train(data='{path}')")
    return 0


def cmd_validate(args) -> int:
    report = get_format(args.format).creator.validate(args.dir)
    if report.ok:
        print(f"{args.dir} is a valid {args.format} dataset.")
        print("Next: kubecore dataset push <dir> <dataset-repo> -m \"message\"")
        return 0
    print(f"{args.dir} has {len(report.errors)} problem(s):", file=sys.stderr)
    print(report.format(), file=sys.stderr)
    return EXIT_INVALID_DATASET


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kubecore", description="KAOS platform tools: datasets and run outputs.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add(parent, name, func, help_, url=True):
        sp = parent.add_parser(name, help=help_, description=help_)
        if url:
            sp.add_argument("--url", help="lakeFS URL (default: LAKEFS_ENDPOINT or .kubecore/dataset-config.yaml)")
        sp.set_defaults(func=func)
        return sp

    add(sub, "login", cmd_login, "sign in through the browser")
    ds = sub.add_parser("dataset", help="create, version, push and pull datasets")
    dsub = ds.add_subparsers(dest="dataset_command", required=True)
    fmts = format_names()

    sp = add(dsub, "create", cmd_create, "create a new dataset repository with a starter layout")
    sp.add_argument("name", help="dataset name (the repository becomes dataset-<name>)")
    sp.add_argument("--classes", help="comma-separated class names, e.g. cat,dog (ultralytics template)")
    sp.add_argument("--description", help="what the dataset is for")
    sp.add_argument("--template", default="ultralytics", choices=fmts + ["yolo", datasets.NO_TEMPLATE],
                    help=f"starter layout ({', '.join(fmts)}), or none for an empty repository (default ultralytics)")
    add(dsub, "list", cmd_list, "list the datasets you can read")
    add(dsub, "versions", cmd_versions, "list a dataset's versions").add_argument("repo")
    add(dsub, "release", cmd_release, "tag the head of main with the next version").add_argument("repo")
    sp = add(dsub, "push", cmd_push, "validate a local folder and open a pull request into the dataset")
    sp.add_argument("dir")
    sp.add_argument("repo", help="dataset repository (created if missing)")
    sp.add_argument("-m", "--message", required=True, help="what changed (pull request title)")
    sp.add_argument("--description", help="description label when the repository is created")
    sp.add_argument("--no-validate", action="store_true", help="skip the format check (prints a warning)")
    sp.add_argument("--format", choices=fmts + ["yolo"],
                    help="format to validate with (default: the repository's template label; none means raw)")
    sp = add(dsub, "pull", cmd_pull, "download a dataset version for training")
    sp.add_argument("ref", help="<repository>@<ref>, e.g. dataset-default@v2 or my-repo@main")
    sp.add_argument("dest", nargs="?", help="folder to download into (default: a per-commit cache)")
    sp.add_argument("--format", choices=fmts + ["yolo"], help="default: the repository's template label, else raw")
    sp.add_argument("--prefix", help="download only this folder of the repository (raw format)")
    sp = add(dsub, "validate", cmd_validate, "check a local folder against the dataset format", url=False)
    sp.add_argument("dir")
    sp.add_argument("--format", default="ultralytics", choices=fmts + ["yolo"])
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValidationFailed as exc:
        print("ERROR: the dataset is not valid, nothing was uploaded:", file=sys.stderr)
        _print_errors(exc.errors)
        return EXIT_INVALID_DATASET
    except KubecoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    except requests.exceptions.ConnectionError as exc:
        print(f"ERROR: cannot reach lakeFS ({exc.__class__.__name__}). Check --url / "
              ".kubecore/dataset-config.yaml and your network.", file=sys.stderr)
        return EXIT_USER_ERROR


if __name__ == "__main__":
    sys.exit(main())
