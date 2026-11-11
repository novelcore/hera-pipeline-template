.PHONY: docs-check
docs-check: ## Check words, removed names and links, then build the docs strictly (needs mkdocs: pip install -r docs/requirements.txt)
	scripts/check-docs.sh
