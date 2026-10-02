# Lido.js template designer — developer entry points.
# Everything assumes the repo root as the working directory.

BACKEND := backend
VENV    := $(BACKEND)/.venv
PY      := $(VENV)/bin/python
UV      := VIRTUAL_ENV=$(PWD)/$(VENV) uv pip install --python $(PWD)/$(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup install infra infra-down db-reset db-upgrade api web dev \
        test lint fmt clean check lido-meta lido-sync lido-add lido-create \
        lido-draft-export lido-doodles

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: install infra lido-add ## One-shot: deps, containers, templates into the database
	@echo "Ready. Run 'make dev' to start the API and the web app."

install: ## Create the venv and install Python + Node dependencies
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(UV) -e "$(BACKEND)[dev]"
	@# CPU-only torch: the default wheel pulls ~3 GB of unusable CUDA libraries.
	$(UV) --extra-index-url https://download.pytorch.org/whl/cpu \
	      --index-strategy unsafe-best-match -e "$(BACKEND)[embed]"
	cd frontend && npm install

infra: ## Start Postgres (pgvector) and MinIO
	docker compose -f infra/docker-compose.yml up -d
	@echo "waiting for Postgres..."
	@until docker compose -f infra/docker-compose.yml exec -T postgres \
	   pg_isready -U design -d design >/dev/null 2>&1; do sleep 1; done
	@echo "infrastructure up"

infra-down: ## Stop the containers (data is preserved)
	docker compose -f infra/docker-compose.yml down

db-reset: ## Drop and recreate the database. Destroys all generations and stored templates.
	docker compose -f infra/docker-compose.yml down -v
	$(MAKE) infra
	$(MAKE) lido-add

db-upgrade: ## Apply infra/initdb/*.sql to the running database (all idempotent)
	@for f in infra/initdb/*.sql; do echo "applying $$f"; \
	  docker compose -f infra/docker-compose.yml exec -T postgres \
	    psql -v ON_ERROR_STOP=1 -q -U design -d design < $$f || exit 1; done

# -- Lido.js templates --------------------------------------------------------------
# Every command works on ALL templates, or on one with TEMPLATE=template_300.
#   make lido-add   [TEMPLATE=x]   ONE new template's whole onboarding: draft metadata
#                                  (only if it needs it) + verify + add to the database
#                                  + embed. Every template not yet in lido_templates,
#                                  or just TEMPLATE=x. A template already in the
#                                  database is left untouched — nothing to redo.
#   make lido-meta  [TEMPLATE=x]   metadata only (draft + verify), no database write
#   make lido-sync  [TEMPLATE=x]   push edits: verify, then re-sync + re-embed a
#                                  template that's already in the database
# FORCE=1: lido-meta re-drafts every template (fills only empty fields, keeps what you
# wrote); lido-sync re-embeds even unchanged templates.
# KIND=post|story|poster|banner|thumbnail|ad|flyer (with lido-meta or lido-add, requires
#   TEMPLATE=x): set that one template's design kind yourself — always wins over the
#   LLM's guess (and over the "post" default), same as if you'd hand-typed it into the
#   template's JSON. Example: make lido-add TEMPLATE=template_300 KIND=banner

_TPL   = $(if $(TEMPLATE),--template $(TEMPLATE))
_DRAFT = $(PY) scripts/enrich_lido_templates.py --draft-slots \
           $(if $(TEMPLATE),--template $(TEMPLATE) --force,$(if $(FORCE),--force)) \
           $(if $(KIND),--kind $(KIND))

# make lido-create [COUNT=5] [AI=1] [SEED=n] [IDEA="..."] [THEME=x] [PALETTE=x] [FONTS=x]
#   generate brand-new template drafts (raw layers + preview PNG) into the database
#   (lido_drafts) for review in the "Design new template" tab — nothing is added to
#   matching until you export one (lido-draft-export) and run lido-add. AI=1 lets the LLM invent the layouts instead
#   of using the built-in recipes. THEME/PALETTE/FONTS pin one choice (names: add
#   --list to the script). Full options: scripts/lido_create_layouts.py --help
lido-create: ## Generate new template drafts for review (saved to the lido_drafts table)
	$(PY) scripts/lido_create_layouts.py --count $(or $(COUNT),5) $(if $(AI),--ai) \
	  $(if $(SEED),--seed $(SEED)) $(if $(IDEA),--idea "$(IDEA)") \
	  $(if $(THEME),--theme $(THEME)) $(if $(PALETTE),--palette $(PALETTE)) \
	  $(if $(FONTS),--fonts $(FONTS))

lido-doodles: ## Check the icon library and draw every icon on a sheet (lidojs_templates/doodles/)
	$(PY) scripts/doodle_sheet.py

lido-draft-export: ## Write a reviewed draft into lidojs_templates/ for lido-add (ID=<draft id> [NAME=template_N])
	$(PY) scripts/lido_drafts.py export $(ID) $(if $(NAME),--name $(NAME)) $(if $(FORCE),--force)

lido-add: ## New template(s) not yet in the database, end to end: metadata + verify + embed + sync
	$(PY) scripts/lido_match.py add $(_TPL) $(if $(KIND),--kind $(KIND))

lido-meta: ## Metadata only, no database write: all templates without it, or TEMPLATE=x (then verify)
	$(_DRAFT)
	$(PY) scripts/enrich_lido_templates.py --verify $(_TPL)

lido-sync: ## Push edits to already-tracked template(s): verify, then sync + embed (TEMPLATE=x or all changed)
	$(PY) scripts/enrich_lido_templates.py --verify $(_TPL)
	$(PY) scripts/lido_match.py index $(_TPL) $(if $(FORCE),--force)

api: ## Run the backend on :8000
	cd $(BACKEND) && .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload

web: ## Run the web app on :5173
	cd frontend && npm run dev

dev: ## Run the API and the web app together
	@$(MAKE) -j2 api web

test: ## Run the test suite
	cd $(BACKEND) && .venv/bin/python -m pytest -q

lint: ## Lint Python and type-check TypeScript
	$(VENV)/bin/ruff check $(BACKEND)/app $(BACKEND)/tests scripts
	cd frontend && npx tsc --noEmit

fmt: ## Auto-fix lint
	$(VENV)/bin/ruff check --fix $(BACKEND)/app $(BACKEND)/tests scripts

check: lint test ## Lint plus tests

clean: ## Remove caches and build output
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache .ruff_cache frontend/dist
