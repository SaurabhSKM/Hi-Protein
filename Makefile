# Hi-Protein - Protein Sovereignty Decision & Offtake Engine
.DEFAULT_GOAL := help
PY := .venv/bin/python
PIP := .venv/bin/pip
PORT ?= 5173

.PHONY: help venv install data train test app serve api web build smoke offline clean reset

help: ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create the Python virtualenv
	python3 -m venv .venv && $(PIP) install -q --upgrade pip

install: venv ## Install backend and frontend dependencies
	$(PIP) install -q -r requirements-dev.txt
	cd frontend && npm install --no-audit --no-fund

data: ## Download the open data and build the training panel (needs network, a few minutes)
	$(PY) ml/build_dataset.py

train: ## Train and conformalise the quantile yield models
	$(PY) ml/train.py

test: ## Run the whole test suite
	$(PY) -m pytest tests/ -q

app: ## Run the app where this workshop container can actually reach it: /app on :8081
	$(PY) scripts/serve_under_app.py

serve: ## Run the whole app (API + built frontend) on one plain port, for local use
	PORT=$(PORT) ./scripts/serve.sh

api: ## Run the API only, with reload, on http://127.0.0.1:$(PORT)
	$(PY) -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port $(PORT)

web: ## Run the frontend dev server on http://127.0.0.1:5173
	cd frontend && npm run dev

build: ## Build the production frontend bundle
	cd frontend && npm run build

smoke: ## Exercise every endpoint against a running API
	$(PY) scripts/smoke.py --port $(PORT)

offline: ## Run from cache only, no network at all, as on untrusted conference wifi
	HIPROTEIN_OFFLINE=1 $(PY) scripts/serve_under_app.py

clean: ## Remove caches and build output
	rm -rf .pytest_cache frontend/dist frontend/.vite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

reset: clean ## Also drop downloaded data and trained artifacts
	rm -rf data/raw data/cache data/processed ml/artifacts/*.joblib ml/artifacts/*.json
