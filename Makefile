# AI Layered Design Generator — developer entry points.
# Everything assumes the repo root as the working directory.

BACKEND := backend
VENV    := $(BACKEND)/.venv
PY      := $(VENV)/bin/python
UV      := VIRTUAL_ENV=$(PWD)/$(VENV) uv pip install --python $(PWD)/$(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup install fonts infra infra-down db-reset seed api web dev \
        test lint fmt eval evals-quick clean check lido-enrich lido-check

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: install fonts infra seed ## One-shot: deps, fonts, containers, template corpus
	@echo "Ready. Run 'make dev' to start the API and the editor."

install: ## Create the venv and install Python + Node dependencies
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(UV) -e "$(BACKEND)[dev]"
	@# CPU-only torch: the default wheel pulls ~3 GB of unusable CUDA libraries.
	$(UV) --extra-index-url https://download.pytorch.org/whl/cpu \
	      --index-strategy unsafe-best-match -e "$(BACKEND)[embed]"
	cd frontend && npm install

fonts: ## Download and instance the variable fonts into static faces
	$(PY) scripts/fetch_fonts.py

infra: ## Start Postgres (pgvector), Redis and MinIO
	docker compose -f infra/docker-compose.yml up -d
	@echo "waiting for Postgres..."
	@until docker compose -f infra/docker-compose.yml exec -T postgres \
	   pg_isready -U design -d design >/dev/null 2>&1; do sleep 1; done
	@echo "infrastructure up"

infra-down: ## Stop the containers (data is preserved)
	docker compose -f infra/docker-compose.yml down

db-reset: ## Drop and recreate the database. Destroys all documents and assets.
	docker compose -f infra/docker-compose.yml down -v
	$(MAKE) infra
	$(MAKE) seed

seed: ## Validate and load the template corpus
	$(PY) scripts/seed_templates.py --rebuild-index

lido-enrich: ## Enrich templates with LLM-generated metadata (default: uses LLM if available)
	$(PY) scripts/enrich_lido_templates.py

lido-enrich-llm: ## Enrich templates using OpenAI LLM (generates smart names, kinds, tags)
	$(PY) scripts/enrich_lido_templates.py

lido-enrich-rule: ## Enrich templates using rule-based generation (no LLM, offline only)
	$(PY) scripts/enrich_lido_templates.py --no-llm

lido-compare: ## Show comparison of LLM vs rule-based enrichment
	$(PY) scripts/compare_enrichment.py

lido-check: ## Exit non-zero if any lidojs_templates/*.json is missing meta
	$(PY) scripts/enrich_lido_templates.py --check

api: ## Run the backend on :8000
	cd $(BACKEND) && .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload

web: ## Run the editor on :5173
	cd frontend && npm run dev

dev: ## Run API and editor together
	@$(MAKE) -j2 api web

test: ## Run the test suite
	cd $(BACKEND) && .venv/bin/python -m pytest -q

lint: ## Lint Python and type-check TypeScript
	$(VENV)/bin/ruff check $(BACKEND)/app $(BACKEND)/tests scripts
	cd frontend && npx tsc --noEmit

fmt: ## Auto-fix lint
	$(VENV)/bin/ruff check --fix $(BACKEND)/app $(BACKEND)/tests scripts

check: lint test ## Lint plus tests

eval: ## Run the full §5.3 evaluation suite (exits non-zero if a gate fails)
	$(PY) scripts/run_evals.py

evals-quick: ## Run five prompts as a smoke test
	$(PY) scripts/run_evals.py --limit 5

clean: ## Remove caches and build output
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache .ruff_cache frontend/dist
