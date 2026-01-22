# Eclipse OBD-II Performance Monitoring System

> Raspberry Pi-based automotive diagnostics and performance monitoring for a 1998 Mitsubishi Eclipse.

## Overview

The Eclipse OBD-II Performance Monitoring System connects to a Bluetooth OBD-II dongle to log vehicle data, provides real-time alerts on an Adafruit 1.3" 240x240 display, performs statistical analysis, and uses AI (ollama with Gemma2/Qwen2.5) to provide performance optimization recommendations focused on air/fuel ratios and engine tuning.

Key features:
- **Auto-start on boot** - Runs headless or with minimal display
- **Real-time monitoring** - RPM, boost pressure, coolant temp alerts
- **Multiple tuning profiles** - Daily, Track, Dyno, Calibration modes
- **Statistical analysis** - Post-drive outlier detection and trends
- **AI recommendations** - Air/fuel ratio optimization via local LLM
- **Data export** - CSV and JSON formats for external analysis
- **Battery backup monitoring** - Graceful shutdown on low power

## Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd OBD2v2

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env.example .env
# Edit .env with your credentials

# Validate configuration
python validate_config.py

# Run the application
python src/main.py --dry-run  # Test run
python src/main.py            # Production run
```

## Project Structure

```
OBD2v2/
├── src/                    # Application source code
│   ├── main.py            # Main entry point with CLI
│   ├── config.json        # Application configuration
│   └── common/            # Shared utilities
│       ├── config_validator.py   # Configuration validation
│       ├── secrets_loader.py     # Environment variable resolution
│       ├── logging_config.py     # Structured logging with PII masking
│       └── error_handler.py      # Error classification and retry logic
│
├── tests/                  # Test suite
│   ├── test_*.py          # Unit tests for each module
│   ├── conftest.py        # Pytest fixtures
│   └── test_utils.py      # Test utilities and helpers
│
├── specs/                  # Project documentation
│   ├── architecture.md    # System architecture
│   ├── methodology.md     # Development methodology
│   ├── standards.md       # Coding standards
│   ├── anti-patterns.md   # Common mistakes to avoid
│   ├── glossary.md        # Domain terminology
│   └── backlog.json       # Task backlog and status
│
├── ralph/                  # Autonomous agent system
│   ├── ralph.sh           # Agent launcher
│   ├── AGENT.md           # Agent instructions
│   ├── ralph_agents.json  # Agent state tracking
│   └── progress.txt       # Session progress notes
│
├── docs/                   # Additional documentation
├── logs/                   # Runtime logs (gitignored)
│
├── requirements.txt        # Python dependencies
├── pyproject.toml         # Project and tool configuration
├── .env.example           # Environment variable template
├── .gitignore             # Git ignore patterns
├── Makefile               # Development commands
├── CLAUDE.md              # Claude Code configuration
└── README.md              # This file
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Application
APP_ENVIRONMENT=development
LOG_LEVEL=INFO

# Database
DB_SERVER=localhost
DB_NAME=eclipse_obd
DB_USER=app_user
DB_PASSWORD=your-secret-password
DB_PORT=1433

# API (for VIN decoder)
API_BASE_URL=https://vpic.nhtsa.dot.gov/api
API_CLIENT_ID=your-client-id
API_CLIENT_SECRET=your-client-secret
```

### Configuration File

Edit `src/config.json` to customize application settings. Secrets are referenced using `${ENV_VAR}` syntax and resolved at runtime:

```json
{
  "database": {
    "password": "${DB_PASSWORD}"
  }
}
```

Supports default values: `${VAR:default_value}`

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_config_validator.py -v

# Skip slow tests
pytest tests/ -m "not slow"

# Single test function
pytest tests/test_main.py::TestParseArgs::test_parseArgs_noArgs_usesDefaults -v
```

### Code Quality

```bash
# Using Make (recommended)
make lint              # Run ruff linter
make lint-fix          # Auto-fix linting issues
make format            # Format with black
make typecheck         # Run mypy type checking
make quality           # Run all quality checks
make pre-commit        # Run quality + tests before committing

# Direct commands
ruff check src/ tests/
black src/ tests/
mypy src/
```

### Application Commands

```bash
# Validate configuration
python validate_config.py --verbose

# Run with different options
python src/main.py --help
python src/main.py --dry-run       # Test without changes
python src/main.py --verbose       # Debug logging
python src/main.py -c config.json  # Custom config file
```

## Common Utilities

The `src/common/` directory contains shared utilities used across the application:

| Module | Purpose |
|--------|---------|
| `config_validator.py` | Validates configuration with required field checks and default application using dot-notation paths |
| `secrets_loader.py` | Resolves `${VAR}` and `${VAR:default}` placeholders from environment variables |
| `logging_config.py` | Structured logging with PII masking (email, phone, SSN) and configurable output |
| `error_handler.py` | Error classification (Retryable/Auth/Config/Data/System), retry decorator with exponential backoff |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](specs/architecture.md) | System design, data flow, component architecture |
| [Methodology](specs/methodology.md) | Development process, TDD workflow, backlog management |
| [Standards](specs/standards.md) | Coding conventions, naming rules, best practices |
| [Anti-Patterns](specs/anti-patterns.md) | Common mistakes and their solutions |
| [Glossary](specs/glossary.md) | Domain terminology and definitions |
| [Backlog](specs/backlog.json) | Task tracking with status and priorities |

## Ralph Autonomous Agent

Ralph is an autonomous development agent that works through the project backlog:

```bash
# Run Ralph for 1 iteration
./ralph/ralph.sh 1

# Run Ralph for 10 iterations
./ralph/ralph.sh 10

# Check Ralph status
make ralph-status
```

See `ralph/AGENT.md` for detailed agent instructions.

## Hardware Requirements

For the full OBD-II monitoring system:
- **Raspberry Pi 3B+ or 4** (4GB RAM recommended for AI models)
- **Adafruit 1.3" 240x240 Color TFT** (ST7789 driver)
- **Bluetooth OBD-II dongle** (ELM327-compatible)
- **12V to 5V adapter** with battery backup (UPS HAT)
- **Voltage monitoring** via ADC or I2C power monitor

## Contributing

1. Create a feature branch from `main`
2. Follow coding standards in `specs/standards.md`
3. Write tests for new functionality (TDD approach)
4. Run `make pre-commit` before committing
5. Update documentation as needed
6. Submit pull request for review

## License

Copyright (c) 2026 Eclipse OBD-II Project. All rights reserved.

---

*Eclipse OBD-II Performance Monitoring System v1.0*
