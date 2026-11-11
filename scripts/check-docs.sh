#!/usr/bin/env bash
# For the maintainers of the template: check the guide, then build it strictly. No GitHub Actions.
# The checks (words, removed names, links across this guide, the kaos-lib guide and the yolo guide) are
# kaos-lib's docs_check.py; this repository holds no copy, so an app created from the template is never checked.
#   scripts/check-docs.sh                         the three checks, then mkdocs --strict
#   scripts/check-docs.sh --external              also check that external links answer
#   DOCS_CHECK_KAOS_LIB=<folder> scripts/...      use this kaos-lib checkout instead of downloading its trunk
#   DOCS_CHECK_YOLO=<folder> scripts/...          the same for the yolo template
#   DOCS_CHECK_OFFLINE=1 scripts/...              this repository alone; it prints what it skipped
set -euo pipefail
cd "$(dirname "$0")/.."
case "$(git remote get-url origin 2>/dev/null || true)" in
  *novelcore/hera-pipeline-template|*novelcore/hera-pipeline-template.git) ;;
  *) echo "check-docs: these checks are for the hera-pipeline-template repository itself; an app created from it has nothing to check here."
     exit 0 ;;
esac
if ! command -v mkdocs >/dev/null; then
  echo "mkdocs not found: python3 -m venv .venv && . .venv/bin/activate && pip install -r docs/requirements.txt" >&2
  exit 2
fi
lib="${DOCS_CHECK_KAOS_LIB:-}"
if [ -z "$lib" ]; then
  lib="$(mktemp -d)"
  trap 'rm -rf "$lib"' EXIT
  if ! curl -fsSL --retry 3 https://codeload.github.com/kaos-io/kaos-lib/tar.gz/refs/heads/main | tar -xz -C "$lib" --strip-components=1; then
    echo "check-docs: cannot download kaos-io/kaos-lib@main, which holds the checks. Try again, or set DOCS_CHECK_KAOS_LIB to a checkout of it." >&2
    exit 1
  fi
fi
if [ ! -f "$lib/docs_check.py" ]; then
  echo "check-docs: $lib has no docs_check.py: it is not a kaos-lib checkout with the docs checks." >&2
  exit 1
fi
if [ "${1:-}" = "--external" ]; then export DOCS_CHECK_EXTERNAL=1; fi
DOCS_CHECK_KAOS_LIB="$lib" python3 "$lib/docs_check.py" "$PWD"
NO_MKDOCS_2_WARNING=1 mkdocs build --strict -d "$(mktemp -d)"
