# ================================================================================
# Makefile - Common Development Commands
# ================================================================================
# Usage: make <target>
# Run 'make help' to see available commands
# ================================================================================

.PHONY: help install install-dev test test-cov lint format typecheck clean run validate ralph deploy deploy-first deploy-status deploy-env

# Default target
.DEFAULT_GOAL := help

# ================================================================================
# Help
# ================================================================================
help: ## Show this help message
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

# ================================================================================
# Installation
# ================================================================================
install: ## Install production dependencies
	pip install -r requirements.txt

install-dev: ## Install all dependencies (including dev tools)
	pip install -r requirements.txt

venv: ## Create virtual environment
	python -m venv .venv
	@echo "Run 'source .venv/bin/activate' (Linux/Mac) or '.venv\\Scripts\\activate' (Windows)"

# ================================================================================
# Testing
# ================================================================================
test: ## Run tests
	pytest tests/ -v

test-cov: ## Run tests with coverage report
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

test-fast: ## Run tests without slow tests
	pytest tests/ -v -m "not slow"

# ================================================================================
# Code Quality
# ================================================================================
lint: ## Run linter (ruff)
	ruff check src/ tests/

lint-fix: ## Run linter and auto-fix issues
	ruff check src/ tests/ --fix

format: ## Format code (black)
	black src/ tests/

format-check: ## Check code formatting without changes
	black src/ tests/ --check

typecheck: ## Run type checker (mypy)
	mypy src/

quality: lint format-check typecheck ## Run all quality checks

# ================================================================================
# Application
# ================================================================================
run: ## Run the application
	python src/main.py

run-dry: ## Run the application in dry-run mode
	python src/main.py --dry-run

validate: ## Validate configuration
	python validate_config.py

validate-verbose: ## Validate configuration with verbose output
	python validate_config.py --verbose

# ================================================================================
# Ralph Agent
# ================================================================================
ralph: ## Run Ralph agent (1 iteration)
	./ralph/ralph.sh

ralph-loop: ## Run Ralph agent (10 iterations)
	./ralph/ralph.sh --loop 10

ralph-status: ## Show Ralph agent status
	@echo "=== Current Task ==="
	@python ralph/get_next_agent.py
	@echo ""
	@echo "=== Recent Progress ==="
	@tail -10 ralph/progress.txt

# ================================================================================
# Deployment (Windows to Raspberry Pi)
# ================================================================================
deploy: ## Deploy to Raspberry Pi via rsync over SSH
	./scripts/deploy.sh

deploy-first: ## First-time deploy (runs pi_setup.sh on Pi before deploy)
	./scripts/deploy.sh --first-run

deploy-status: ## Check eclipse-obd service status on Pi
	@. deploy/deploy.conf && ssh -o ConnectTimeout=5 -p $${PI_PORT} $${PI_USER}@$${PI_HOST} "sudo systemctl status eclipse-obd"

deploy-env: ## Copy .env file to Pi (one-time secrets push with confirmation)
	./scripts/deploy-env.sh

# ================================================================================
# Cleanup
# ================================================================================
clean: ## Remove build artifacts and cache
	rm -rf __pycache__ .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache
	rm -rf build/ dist/ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: clean ## Remove all artifacts including virtual environment
	rm -rf .venv

# ================================================================================
# Development Workflow
# ================================================================================
dev-setup: venv install-dev ## Full development setup
	@echo "Development environment ready!"
	@echo "Don't forget to:"
	@echo "  1. Activate venv: source .venv/bin/activate"
	@echo "  2. Copy .env: cp .env.example .env"
	@echo "  3. Edit .env with your values"

pre-commit: quality test ## Run before committing (quality checks + tests)
	@echo "All checks passed! Ready to commit."
