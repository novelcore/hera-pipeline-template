#!/usr/bin/env bash
# Check the guide and build it strictly. Local use or the platform's build; no GitHub Actions.
# The build runs scripts/docs_check.py first (words, removed names, links across this guide, the kaos-lib guide
# and the yolo guide), so a finding fails it.
#   scripts/check-docs.sh                        the three checks, then mkdocs --strict
#   scripts/check-docs.sh --external             also check that external links answer
#   DOCS_CHECK_OFFLINE=1 scripts/check-docs.sh   no network: this repository alone
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v mkdocs >/dev/null; then
  echo "mkdocs not found: python3 -m venv .venv && . .venv/bin/activate && pip install -r docs/requirements.txt" >&2
  exit 2
fi
if [ "${1:-}" = "--external" ]; then export DOCS_CHECK_EXTERNAL=1; fi
NO_MKDOCS_2_WARNING=1 exec mkdocs build --strict -d "$(mktemp -d)"
