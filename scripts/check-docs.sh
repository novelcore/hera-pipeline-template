#!/usr/bin/env bash
# Build the docs strictly and check every link. Local use or Argo; no GitHub Actions.
#   scripts/check-docs.sh              mkdocs --strict + internal links and anchors
#   scripts/check-docs.sh --external   also check that external links answer
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v mkdocs >/dev/null; then
  echo "mkdocs not found: python3 -m venv .venv && . .venv/bin/activate && pip install -r docs/requirements.txt" >&2
  exit 2
fi
NO_MKDOCS_2_WARNING=1 mkdocs build --strict -d "$(mktemp -d)"
exec python3 scripts/check_links.py "$@"
