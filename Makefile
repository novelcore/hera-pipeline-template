.PHONY: docs-check
docs-check: ## Build the docs strictly and check every link (needs mkdocs: pip install -r docs/requirements.txt)
	scripts/check-docs.sh
