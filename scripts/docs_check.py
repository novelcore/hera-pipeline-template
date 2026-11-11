#!/usr/bin/env python3
"""Three checks of the client documentation: words, removed names, links.

The same file is kept in three repositories, because their pages form one guide and link to each other:
kaos-io/kaos-lib (docs_check.py), novelcore/hera-pipeline-template and novelcore/yolo-pipelines-template
(scripts/docs_check.py). Change it in all three.

It is a mkdocs hook, so `mkdocs build` fails on a finding, and it runs by hand: `python3 docs_check.py`.

  words          client pages never name what the platform is built from
  removed names  nothing describes a step or a folder that no longer exists
  links          every link of this repository resolves, in this repository and in the other two, and every
                 link of the other two into this repository resolves

The other two repositories are read at their trunk. Settings, all optional, are environment variables:

  DOCS_CHECK_KAOS_LIB, DOCS_CHECK_HERA, DOCS_CHECK_YOLO   a checkout to read instead of downloading the trunk
  DOCS_CHECK_OFFLINE=1    this repository alone: links to and from the other two are not checked, and it says so
  DOCS_CHECK_EXTERNAL=1   also fetch every other http(s) link of this repository

By hand, a trunk that cannot be downloaded is an error. In a build it is not: the site must build without the
network, so the build goes on and says which links it did not check.
"""
from __future__ import annotations

import atexit
import io
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request

BUCKET = "https://storage.googleapis.com/kaos-dev-511509-kaos-lib/"
REPOS = {
    "KAOS_LIB": {
        "repo": "kaos-io/kaos-lib", "trunk": "main",
        "sites": (BUCKET + "docs/",),
        "generated": ("docs/generated/cli.md",),             # written by the build (docs_gen.py), not committed
        # Not client pages: the changelog records history, removed names included; docs/design/ is for the platform team.
        "not_client": ("CHANGELOG.md", "docs/design/"),
        "wave": (),
    },
    "HERA": {
        "repo": "novelcore/hera-pipeline-template", "trunk": "dev",
        "sites": ("https://novelcore.github.io/hera-pipeline-template/", BUCKET + "template-docs/hera-pipeline-template/"),
        "generated": (), "not_client": (),
        # Rewritten or deleted with the new step contract (PRD kaos#1911 G4); remove an entry when its page is done.
        "wave": ("DEVELOPER.md", "docs/write-a-step.md"),
    },
    "YOLO": {
        "repo": "novelcore/yolo-pipelines-template", "trunk": "dev",
        "sites": ("https://novelcore.github.io/yolo-pipelines-template/", BUCKET + "template-docs/yolo-pipelines-template/"),
        "generated": (), "not_client": (),
        "wave": ("DEVELOPER.md", "ADD-A-STEP.md"),          # as above
    },
}

# (pattern, what it is, what to write instead). Matched without case, on the text a reader sees (not on link targets).
WORDS = (
    (r"\bargo(?:cd)?\b", "the workflow engine's name", 'write "the run page", "the run form" or "the platform"'),
    (r"\bkubectl\b", "a cluster command", "clients have no cluster access: name the console page or the kaosctl command"),
    (r"\bnamespaces?\b", "a cluster word", 'write "project"'),
    (r"\bcrossplane\b", "a platform component", 'write "the platform"'),
    (r"\bkubecore-(?:dev|prod)-kaos[\w-]*|\bkaos-v3\b|\bgke-(?:dev|prod)\b|\bprd240-kaos\b", "a cluster name",
     'write "the platform" or "your project\'s machines"'),
)
REMOVED = (
    (r"\bdataset[-_]loading\b", "the dataset-loading step was removed: the platform pins the run's dataset"),
    (r"\bdata[-_]summary\b", "the data-summary step was removed from the templates"),
    (r"\bcompose[-_]and[-_]validate\b", "the compose-and-validate step was removed: the platform composes the parameters"),
    (r"(?<![\w./~-])kubecore/", "an app holds no kubecore/ folder: the platform runs its own pipeline engine"),
)

SKIP_DIRS = {"node_modules", "site", "venv", "build", "dist", "out", "__pycache__", "generated"}
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)|^\s*\[[^\]]+\]:\s+(\S+)", re.M)
URL = re.compile(r"https?://[^\s)>\]\"'`|]+")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_fetched: dict = {}


class CannotDownload(Exception):
    pass


def find_root(start: pathlib.Path) -> pathlib.Path:
    for folder in (start, *start.parents):
        if (folder / "mkdocs.yml").is_file():
            return folder
    raise SystemExit(f"docs check: no mkdocs.yml in {start} or above it")


def key_of(root: pathlib.Path) -> str:
    """Which of the three repositories `root` is, from `repo_name` in its mkdocs.yml."""
    m = re.search(r"^repo_name:\s*(\S+)", (root / "mkdocs.yml").read_text(encoding="utf-8"), re.M)
    for key, spec in REPOS.items():
        if m and m.group(1) == spec["repo"]:
            return key
    raise SystemExit(f"docs check: {root / 'mkdocs.yml'} names none of the three repositories in repo_name")


def pages(root: pathlib.Path) -> list:
    """Every Markdown file of the repository, without hidden folders, environments and build output."""
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        found += [pathlib.Path(folder, n) for n in sorted(names) if n.endswith(".md")]
    return found


def listed(rel: str, entries) -> bool:
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in entries)


def visible(line: str) -> str:
    """The line as a reader sees it: without link targets and bare addresses."""
    return URL.sub("", re.sub(r"\]\([^)]*\)", "]", line))


# ------------------------------------------------------------------ words and removed names
def check_text(root: pathlib.Path, key: str) -> tuple:
    spec = REPOS[key]
    words, removed = [], []
    for path in [*pages(root), root / "mkdocs.yml"]:
        rel = path.relative_to(root).as_posix()
        if listed(rel, spec["not_client"]) or listed(rel, spec["wave"]):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            seen = visible(line)
            for pattern, what, instead in WORDS:
                for m in re.finditer(pattern, seen, re.I):
                    words.append(f"{rel}:{number}: \"{m.group(0)}\" is {what}; {instead}")
            for pattern, why in REMOVED:
                for m in re.finditer(pattern, line, re.I):
                    removed.append(f"{rel}:{number}: \"{m.group(0)}\": {why}")
    return words, removed


# ------------------------------------------------------------------ links
def slug(heading: str) -> str:
    """The anchor mkdocs gives a heading (Python-Markdown's toc slugify)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>|[`*]", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", text).strip().lower())


def anchors(path: pathlib.Path) -> set:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    out, count = set(re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", text)), {}
    for m in HEADING.finditer(text):
        heading = m.group(1)
        explicit = re.search(r"\{:?\s*#([\w-]+)[^}]*\}\s*$", heading)
        base = explicit.group(1) if explicit else slug(heading)
        count[base] = count.get(base, 0) + 1
        out.add(base if count[base] == 1 else f"{base}_{count[base] - 1}")
    return out


def in_repo(url: str):
    """(repository key, path in the repository) for an address of one of the three repositories, else None."""
    url = url.split("#")[0].split("?")[0]
    for key, spec in REPOS.items():
        m = re.match(rf"https://github\.com/{re.escape(spec['repo'])}/(?:blob|tree)/[^/]+/(.+)", url)
        if m:
            return key, m.group(1).rstrip("/")
        for site in spec["sites"]:
            if url.startswith(site):
                page = url[len(site):]
                if page in ("", "index.html"):
                    return key, "docs/index.md"
                if page.endswith(".html"):
                    return key, f"docs/{page[:-5]}.md"
                if page.endswith("/"):
                    return key, f"docs/{page[:-1]}.md"
                return key, f"docs/{page}"
    return None


def missing(tree: pathlib.Path, key: str, rel: str, fragment: str) -> str:
    """Why `rel#fragment` does not resolve in the checkout `tree` of repository `key`; empty when it does."""
    if rel in REPOS[key]["generated"]:
        return ""
    target = tree / rel
    if not target.exists() and rel.startswith("docs/") and rel.endswith(".md"):
        target = tree / rel[:-3] / "index.md"            # a folder address: <page>/ is <page>/index.md
    if not target.exists():
        return "no such file"
    if fragment and target.suffix == ".md" and fragment not in anchors(target):
        return f"no heading with the anchor #{fragment}"
    return ""


def links(path: pathlib.Path) -> list:
    """(line number, target) of every link of a file: Markdown links outside code, and addresses anywhere."""
    text = path.read_text(encoding="utf-8")
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))      # keep the line numbers
    prose = INLINE_CODE.sub(blank, FENCE.sub(blank, text)) if path.suffix == ".md" else ""
    found = {(prose.count("\n", 0, m.start()) + 1, m.group(1) or m.group(2)) for m in LINK.finditer(prose)}
    found |= {(text.count("\n", 0, m.start()) + 1, m.group(0).rstrip(".,;:")) for m in URL.finditer(text)}
    return sorted(found)


def fetch(key: str) -> pathlib.Path:
    """The trunk of another repository, downloaded once (the three repositories are public)."""
    if key not in _fetched:
        spec = REPOS[key]
        url = f"https://codeload.github.com/{spec['repo']}/tar.gz/refs/heads/{spec['trunk']}"
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "docs-check"}), timeout=60) as r:
                    raw = r.read()
                break
            except Exception as exc:  # noqa: BLE001 - any network failure is reported the same way
                last = exc
                time.sleep(3 * (attempt + 1))
        else:
            raise CannotDownload(f"cannot download {spec['repo']}@{spec['trunk']} ({last})")
        dest = pathlib.Path(tempfile.mkdtemp(prefix="docs-check-"))
        atexit.register(shutil.rmtree, dest, True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(dest)
        _fetched[key] = next(p for p in dest.iterdir() if p.is_dir())
    return _fetched[key]


def answers(url: str) -> bool:
    for attempt in range(3):
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method, headers={"User-Agent": "docs-check"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status < 400
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    time.sleep(3 * (attempt + 1))
                    break
                if method == "GET":
                    return False
            except Exception:  # noqa: BLE001
                if method == "GET":
                    return False
    return True     # still rate-limited: unknown, not broken


def check_links(root: pathlib.Path, key: str, env, must_download: bool) -> tuple:
    offline = env.get("DOCS_CHECK_OFFLINE") == "1"
    trees, skipped = {key: root}, []
    for other in REPOS:
        if other != key and not offline:
            given = env.get(f"DOCS_CHECK_{other}")
            try:
                trees[other] = pathlib.Path(given).resolve() if given else fetch(other)
            except CannotDownload as exc:
                if must_download:
                    raise SystemExit(f"docs check: {exc}. Set DOCS_CHECK_{other} to a checkout of it, or "
                                     f"DOCS_CHECK_OFFLINE=1 to check this repository alone.") from None
                skipped.append(str(exc))
                continue
            if not (trees[other] / "mkdocs.yml").is_file():
                raise SystemExit(f"docs check: DOCS_CHECK_{other}={given} is not a checkout of {REPOS[other]['repo']}")
    bad, external, unchecked = [], {}, 0
    for path in [*pages(root), root / "mkdocs.yml"]:
        rel = path.relative_to(root).as_posix()
        for number, target in links(path):
            where = f"{rel}:{number}"
            if target.startswith(("mailto:", "tel:")):
                continue
            if target.startswith(("http://", "https://")):
                hit = in_repo(target)
                if hit is None:
                    external.setdefault(target.split("#")[0], where)
                elif hit[0] not in trees:
                    unchecked += 1
                else:
                    why = missing(trees[hit[0]], hit[0], hit[1], target.partition("#")[2])
                    if why:
                        bad.append(f"{where}: {target}: {why} in {REPOS[hit[0]]['repo']} ({hit[1]})")
                continue
            file, _, fragment = target.partition("#")
            dest = path if not file else (path.parent / file.split("?")[0])
            dest_rel = os.path.relpath(dest, root).replace(os.sep, "/")
            why = missing(root, key, dest_rel, fragment) if not dest_rel.startswith("..") else "points outside the repository"
            if why:
                bad.append(f"{where}: {target}: {why}")
    for other, tree in trees.items():                         # what the other two say about this repository
        if other == key:
            continue
        for path in [*pages(tree), tree / "mkdocs.yml"]:
            for number, target in links(path):
                hit = in_repo(target) if target.startswith("https://") else None
                if hit and hit[0] == key:
                    why = missing(root, key, hit[1], target.partition("#")[2])
                    if why:
                        bad.append(f"{REPOS[other]['repo']}@{REPOS[other]['trunk']} {path.relative_to(tree).as_posix()}:{number} "
                                   f"links to {target}: {why} here ({hit[1]})")
    if env.get("DOCS_CHECK_EXTERNAL") == "1":
        bad += [f"{where}: {url}: does not answer" for url, where in sorted(external.items()) if not answers(url)]
    note = f"{len(external)} other addresses" + ("" if env.get("DOCS_CHECK_EXTERNAL") == "1" else " not fetched")
    if len(trees) > 1:
        note += "; with " + ", ".join(f"{REPOS[o]['repo']} at {t}" for o, t in trees.items() if o != key)
    if offline or skipped:
        note += (f"; NOT CHECKED: {unchecked} links into the other repositories and their links into this one"
                 + (" (DOCS_CHECK_OFFLINE=1)" if offline else f" ({'; '.join(skipped)})"))
    return bad, note


# ------------------------------------------------------------------ entry points
def run(root: pathlib.Path, env=os.environ, must_download: bool = True) -> tuple:
    """(report text, number of findings) of the three checks on the repository at `root`."""
    key = key_of(root)
    words, removed = check_text(root, key)
    broken, note = check_links(root, key, env, must_download)
    out = [f"docs check of {REPOS[key]['repo']} ({root})"]
    for title, found, hint in (
            ("words", words, "client pages never name what the platform is built from"),
            ("removed names", removed, "these no longer exist: delete the line or describe what replaced it"),
            ("links", broken, note)):
        out.append(f"  {title}: {len(found)} finding{'' if len(found) == 1 else 's'} ({hint})")
        out += [f"    {line}" for line in found]
    return "\n".join(out), len(words) + len(removed) + len(broken)


def on_pre_build(config, **kwargs):
    """mkdocs hook: a finding stops the build."""
    from mkdocs.exceptions import PluginError
    report, findings = run(find_root(pathlib.Path(config["config_file_path"]).resolve().parent), must_download=False)
    print(report)
    if findings:
        raise PluginError(f"docs check: {findings} findings, listed above")


if __name__ == "__main__":
    text, count = run(find_root(pathlib.Path(__file__).resolve().parent))
    print(text)
    sys.exit(1 if count else 0)
