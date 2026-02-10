.PHONY: lint format check typecheck test test-unit test-integration test-fast clean

PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff

## Linting & Formatting

format: ## Formata codigo com ruff
	$(RUFF) format src/ tests/

lint: ## Roda ruff check (lint)
	$(RUFF) check src/ tests/

typecheck: ## Roda mypy (type checking)
	$(PYTHON) -m mypy src/

check: format lint typecheck ## Formata + lint + typecheck (tudo)

## Testes

test: ## Roda todos os testes
	$(PYTHON) -m pytest tests/ -q

test-unit: ## Roda apenas testes unitarios
	$(PYTHON) -m pytest tests/unit/ -q

test-integration: ## Roda apenas testes de integracao
	$(PYTHON) -m pytest tests/integration/ -q

test-fast: ## Roda testes sem os marcados como slow
	$(PYTHON) -m pytest tests/ -q -m "not slow"

## CI (simula pipeline local)

ci: format lint typecheck test ## Pipeline completa: format + lint + typecheck + testes

## Utilidades

clean: ## Remove artefatos de build e cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info

proto: ## Gera stubs protobuf
	bash scripts/generate_proto.sh

help: ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
