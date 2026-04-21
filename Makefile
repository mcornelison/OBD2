# ================================================================================
# Makefile - Common Development Commands
# ================================================================================
# Usage: make <target>
# Run 'make help' to see available commands
# ================================================================================

.PHONY: help install install-dev test test-cov lint lint-addresses format typecheck clean run validate ralph deploy deploy-first deploy-restart deploy-status

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
lint: ## Run linter (ruff) -- src/ tests/ + scripts/ + validate_config.py + offices/{pm,ralph}/*.py (US-207 TD-018 widened scope)
	ruff check src/ tests/ scripts/ validate_config.py offices/pm/scripts offices/ralph/agent.py specs/golden_code_sample.py

lint-fix: ## Run linter and auto-fix issues
	ruff check src/ tests/ scripts/ validate_config.py offices/pm/scripts offices/ralph/agent.py specs/golden_code_sample.py --fix

format: ## Format code (black)
	black src/ tests/

format-check: ## Check code formatting without changes
	black src/ tests/ --check

typecheck: ## Run type checker (mypy)
	mypy src/

lint-addresses: ## B-044 audit -- fail if hardcoded infrastructure addresses exist outside config.json
	bash scripts/audit_config_literals.sh

quality: lint format-check typecheck ## Run all quality checks

# ================================================================================
# Application
# ================================================================================
run: ## Run the Pi application
	python src/pi/main.py

run-dry: ## Run the Pi application in dry-run mode
	python src/pi/main.py --dry-run

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
	@python ralph/agent.py list
	@echo ""
	@python ralph/agent.py sprint

# ================================================================================
# Deployment (Windows to Raspberry Pi)
# ================================================================================
deploy: ## Deploy to Raspberry Pi via rsync over SSH
	bash deploy/deploy-pi.sh

deploy-first: ## First-time Pi bootstrap (--init: wipe legacy dirs, create venv, set hostname)
	bash deploy/deploy-pi.sh --init

deploy-restart: ## Bounce the eclipse-obd service on the Pi
	bash deploy/deploy-pi.sh --restart

deploy-status: ## Check eclipse-obd service status on Pi
	@. deploy/deploy.conf && ssh -o ConnectTimeout=5 $${PI_USER}@$${PI_HOST} "sudo systemctl status eclipse-obd"

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
