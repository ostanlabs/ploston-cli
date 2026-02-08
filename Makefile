# Ploston CLI
# ===========
# Development commands for local testing and PyPI publishing
#
# Quick start:
#   make install    # Install dependencies
#   make test       # Run tests
#   make build      # Build package

# Configuration
PYTHON = uv run python
PYTEST = uv run pytest
PACKAGE_NAME = ploston-cli

# Colors
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

.PHONY: help install test lint format build publish-test publish clean

# =============================================================================
# HELP
# =============================================================================

help:
	@echo ""
	@echo "$(CYAN)Ploston CLI$(RESET)"
	@echo "==========="
	@echo ""
	@echo "$(GREEN)Development:$(RESET)"
	@echo "  make install      Install dependencies with uv"
	@echo "  make test         Run all tests"
	@echo "  make test-unit    Run unit tests only"
	@echo "  make lint         Run ruff linter"
	@echo "  make format       Format code with ruff"
	@echo "  make check        Run lint + format check + tests"
	@echo ""
	@echo "$(GREEN)Build & Publish:$(RESET)"
	@echo "  make build        Build package (sdist + wheel)"
	@echo "  make publish-test Publish to TestPyPI"
	@echo "  make publish      Publish to PyPI"
	@echo ""
	@echo "$(GREEN)Maintenance:$(RESET)"
	@echo "  make clean        Remove build artifacts"
	@echo ""

# =============================================================================
# DEVELOPMENT
# =============================================================================

## Install dependencies
install:
	@echo "$(CYAN)Installing dependencies...$(RESET)"
	uv sync --all-extras
	@echo "$(GREEN)Done!$(RESET)"

## Run all tests
test:
	@echo "$(CYAN)Running all tests...$(RESET)"
	$(PYTEST) tests/ -v

## Run unit tests only
test-unit:
	@echo "$(CYAN)Running unit tests...$(RESET)"
	$(PYTEST) tests/unit/ -v

## Run tests with coverage
test-cov:
	@echo "$(CYAN)Running tests with coverage...$(RESET)"
	$(PYTEST) tests/ -v --cov=ploston_cli --cov-report=html --cov-report=term

## Run linter
lint:
	@echo "$(CYAN)Running linter...$(RESET)"
	uv run --all-extras ruff check src/ tests/
	uv run --all-extras ruff format --check src/ tests/

## Format code
format:
	@echo "$(CYAN)Formatting code...$(RESET)"
	uv run --all-extras ruff format src/ tests/
	uv run --all-extras ruff check --fix src/ tests/

## Run all checks
check: lint test
	@echo "$(GREEN)All checks passed!$(RESET)"

# =============================================================================
# BUILD & PUBLISH
# =============================================================================

## Build package
build: clean
	@echo "$(CYAN)Building package...$(RESET)"
	uv build
	@echo "$(GREEN)Build complete!$(RESET)"
	@ls -la dist/

## Build dev package (with timestamp-based version)
build-dev: clean
	@echo "$(CYAN)Building dev package...$(RESET)"
	DEV_VERSION=$$(date +%s) && \
	sed -i.bak "s/^version = .*/version = \"0.1.0.dev$$DEV_VERSION\"/" pyproject.toml && \
	uv build && \
	mv pyproject.toml.bak pyproject.toml
	@echo "$(GREEN)Build complete!$(RESET)"
	@ls -la dist/

## Publish to TestPyPI
publish-test: build
	@echo "$(CYAN)Publishing to TestPyPI...$(RESET)"
	uv publish --publish-url https://test.pypi.org/legacy/
	@echo "$(GREEN)Published to TestPyPI!$(RESET)"
	@echo "Install with: pip install -i https://test.pypi.org/simple/ $(PACKAGE_NAME)"

## Publish dev package to TestPyPI (requires UV_PUBLISH_TOKEN env var)
publish-test-pypi:
	@echo "$(CYAN)Publishing to TestPyPI...$(RESET)"
	uv publish --publish-url https://test.pypi.org/legacy/
	@echo "$(GREEN)Published to TestPyPI!$(RESET)"

## Publish to PyPI
publish: build
	@echo "$(CYAN)Publishing to PyPI...$(RESET)"
	uv publish
	@echo "$(GREEN)Published to PyPI!$(RESET)"
	@echo "Install with: pip install $(PACKAGE_NAME)"

# =============================================================================
# MAINTENANCE
# =============================================================================

## Remove build artifacts
clean:
	@echo "$(CYAN)Cleaning build artifacts...$(RESET)"
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Clean!$(RESET)"

