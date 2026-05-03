# OpenRTC developer convenience targets.
# All commands delegate to `uv run` so they pick up the locked dev environment.
# Run `uv sync --group dev` once to set up the environment, then use these targets.

.PHONY: help install test test-fast lint format format-check typecheck dev bench clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install package and dev dependencies via uv
	uv sync --group dev

test: ## Run the test suite with coverage
	uv run pytest --cov=openrtc --cov-report=term-missing --cov-fail-under=80

test-fast: ## Run tests without coverage (faster feedback loop)
	uv run pytest -q

lint: ## Run Ruff lint checks
	uv run ruff check .

format: ## Auto-format code with Ruff
	uv run ruff format .

format-check: ## Check formatting without making changes (used in CI)
	uv run ruff format --check .

typecheck: ## Run mypy type checks on the source tree
	uv run mypy src/

dev: ## Validate agent discovery without a LiveKit server (set --agents-dir as needed)
	uv run openrtc list ./examples/agents \
		--default-stt "deepgram/nova-3:multi" \
		--default-llm "openai/gpt-4.1-mini" \
		--default-tts "cartesia/sonic-3"

bench: ## Run the v0.1 density benchmark (50 sessions, 4 GB peak RSS gate)
	uv run python tests/benchmarks/density.py --sessions 50 --rss-budget-mb 4096

clean: ## Remove build artefacts and __pycache__ directories
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist build .coverage coverage.xml htmlcov .mypy_cache .ruff_cache
