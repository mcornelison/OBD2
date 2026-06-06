# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Type

Python 3.11+ development template with TDD methodology, comprehensive specs, and Ralph autonomous agent system.

## A2AL/0.4.1 — Agent-to-Agent Communication

This project uses [A2AL/0.4.1](https://github.com/mcornelison/A2AL) for peer-to-peer agent messages. The team-adopted authoritative reference is `offices/handbook.md` §9 (synced upstream). v0.4.1 supersedes v0.4.0 team-wide as of 2026-05-22.

### Identity for A2AL routing headers

When sending A2AL messages, sign as `<Name>/<role>` or `<Name>(<role>)` in the routing header. Current team:

| Agent | Role | Office |
|---|---|---|
| Marcus | PM | `offices/pm/` |
| Atlas | Architect | `offices/architect/` |
| Argus | QA / Tester | `offices/tester/` |
| Spool | Tuning SME | `offices/tuner/` |
| Ralph (Rex) | Dev | `offices/ralph/` |
| Iris | UI/UX | `offices/uidevloper/` |

### When to use A2AL (audience rule, normative — v0.4.1 §2.1)

- **Agent → agent, no human review expected → A2AL MUST.**
- **Human in the audience → Markdown.**
- **Inbound said `audience=agent` or sender ID'd as an AI agent → reply MUST be A2AL** (reactive rule).
- **Default → Markdown** when audience is ambiguous or mixed.
- **RCAs / ADRs / design specs / long-form deliberation → Markdown** (humans return to these).

### Routing header (mandatory on every A2AL message — v0.4.1 §3)

```text
from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<short label>
```

Fields separated by `; `. One line, ends at first newline. Optional fields: `audience=agent|mixed`, `urgency=low|medium|high|urgent`, `refs=<id>,<id>`, `in-reply-to=<id>`. Multiple recipients comma-separated: `to=Atlas(Architect), Marcus(PM)`.

### v0.4.1 changes vs v0.4.0

1. **Audience rule** (§2.1) is now MUST, not SHOULD. No hybrid mode; no duplication.
2. **Routing header** (§3) is mandatory. Every message starts with the one-line header.
3. **`cc: CIO` is retired.** CIO retains filesystem visibility into any inbox at any time; the explicit cc line was redundant. (Old v0.4.0 archive headers stay readable; no migration of historical files needed.)

### Inboxes

- Each agent's inbox: `offices/<role>/inbox/`
- Filename: `YYYY-MM-DD-from-<sender>-<short-slug>.md`
- Threading: reference prior message in body — `re: <id>` or `in-reply-to: <id>`

### Reference

- Team-adopted spec: `offices/handbook.md` §9
- Upstream spec + library: https://github.com/mcornelison/A2AL
- Each agent's local skill: `offices/<role>/.claude/skills/a2al/SKILL.md` + `offices/<role>/.claude/commands/a2al.md`

## Shared-Checkout Discipline (Multi-Agent Concurrency) — CORE BOOTUP

All agents share ONE working checkout (`Z:\o\OBD2v2`) on the chi-nas-01 SMB share. Branch switches and concurrent commits **race** — edits, staging, and even committed work can be silently lost. Every agent follows this (ratified CIO 2026-06-01; full text `offices/handbook.md` §13):

1. **Commit-immediately, office-scoped** — `add`+`commit` your own `offices/<role>/**` in small commits right after each edit-set. Never leave work uncommitted across turns (that's what disappears on a branch switch).
2. **Only the PM (Marcus) switches branches / merges / deploys** — no other agent runs `git checkout`/`switch`/`merge`/`rebase`. Stay on the live branch and commit there; the PM integrates.
3. **PM announces + waits for a quiet window before switching branches.**
4. **Retry-on-lock, never force** — a stale `.git/index.lock` from the slow share clears in seconds; wait + retry; never delete it while a `git` process is running.
5. **"file modified since read"** in Edit = another agent is writing it → re-read + re-apply; prefer editing only your own office.

## Development Commands

### Testing
```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_config_validator.py -v

# Run without slow tests
pytest tests/ -v -m "not slow"

# Single test function
pytest tests/test_config_validator.py::TestConfigValidator::test_validate_validConfig_returnsConfig -v
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
ruff check src/ tests/ --fix
black src/ tests/
mypy src/
```

### Application
```bash
# Validate configuration
python validate_config.py
python validate_config.py --verbose

# Run Pi application (tier entry point)
python src/pi/main.py
python src/pi/main.py --dry-run
python src/pi/main.py --config path/to/config.json

# Run Pi application in simulator mode (no OBD hardware needed)
python src/pi/main.py --simulate --dry-run
```

### Ralph Agent System
```bash
# Run Ralph agent (1 iteration)
./offices/ralph/ralph.sh 1

# Run Ralph agent (10 iterations)
./offices/ralph/ralph.sh 10

# Check Ralph status
make ralph-status
```

## Architecture Overview

The project is a 3-tier distributed system. See `offices/ralph/CLAUDE.md` for
the architectural decisions and tier boundaries. The `src/` tree is split
into `common/` (shared), `pi/` (Raspberry Pi edge), and `server/` (Chi-Srv-01).

### Configuration System (3-Layer)
The project uses a sophisticated configuration system with three layers:

1. **Environment Variables** (`.env`) - Secrets only, never committed
2. **Secrets Loader** (`src/common/config/secrets_loader.py`) - Resolves `${ENV_VAR}` placeholders at runtime
3. **Config Validator** (`src/common/config/validator.py`) - Validates schema, applies defaults, ensures required fields

`config.json` lives at the repo root and has a tier-aware shape: top-level
shared keys (`protocolVersion`, `schemaVersion`, `deviceId`, `logging`) plus
`pi:` and `server:` sections for tier-specific settings. Consumer pattern:
`config.get('pi', {}).get('<section>', ...)` for Pi sections,
`config.get('server', {}).get('ai', ...)` for server AI config.

**Critical Pattern**: In `config.json`, use `${ENV_VAR}` syntax for secrets:
```json
{
  "database": {
    "password": "${DB_PASSWORD}"
  }
}
```

The validator uses dot-notation paths for nested defaults:
```python
DEFAULTS = {
    'database.timeout': 30,
    'api.retry.maxRetries': 3
}
```

### Error Classification System
Errors follow a 5-tier classification (`src/common/errors/handler.py`):

1. **Retryable** (network timeouts, rate limits) → Exponential backoff retry
2. **Authentication** (401/403, credentials issues) → Fail, log credentials issue
3. **Configuration** (missing settings, invalid values) → Fail fast with clear message
4. **Data** (validation failures) → Log and continue/skip
5. **System** (unexpected errors) → Fail with full diagnostics

Retry pattern uses: `[1, 2, 4, 8, 16]` second delays with max 3 retries.

### Common Utilities Pattern
All utilities in `src/common/` follow these patterns:
- File headers required (see `specs/standards.md`)
- camelCase for functions/variables, PascalCase for classes
- Type hints on all public functions
- Google-style docstrings with Args/Returns/Raises
- Comprehensive error handling with specific exception types

## Coding Standards (Critical Points)

### Naming Conventions (STRICT)
- **Python functions/variables**: camelCase (`getUserData`, `recordCount`)
- **Python classes**: PascalCase (`ConfigValidator`, `DataProcessor`)
- **SQL tables/columns**: snake_case (`user_accounts`, `created_at`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_RETRIES`, `DEFAULT_TIMEOUT`)

### File Headers (REQUIRED)
Every Python file must include the standard header. See `specs/standards.md` line 16-33 for the exact format.

### Documentation Requirements
- Public functions require Google-style docstrings
- Complex logic requires inline comments explaining "why" not "what"
- No comments for self-explanatory code

## Specs System

The `specs/` directory contains developer reference material:

| File | Purpose |
|------|---------|
| `standards.md` | Complete coding conventions (naming, headers, SQL, testing) |
| `architecture.md` | System design, data flow, technology stack |
| `methodology.md` | TDD workflow, error handling strategy |
| `anti-patterns.md` | Common mistakes and their solutions |
| `glossary.md` | Domain terminology |
| `best-practices.md` | Industry best practices: Python, SQL, REST API, design patterns |
| `grounded-knowledge.md` | Authoritative sources, vehicle facts, safe operating ranges (PM Rule 7) |
| `obd2-research.md` | OBD-II protocol research, PID tables, polling strategy |

## Project Management

The `offices/pm/` directory contains all planning and tracking artifacts:

| Location | Purpose |
|----------|---------|
| `offices/pm/projectManager.md` | PM identity, rules, session memory, decisions |
| `offices/pm/roadmap.md` | Phase tracking and backlog summary |
| `offices/pm/backlog.json` | Hierarchical backlog (Epic > Feature > Story) |
| `offices/pm/story_counter.json` | Global sequential story ID counter (US-101+) |
| `offices/pm/backlog/B-*.md` | Active backlog items (detailed descriptions) |
| `offices/pm/prds/prd-*.md` | Active Product Requirements Documents |
| `offices/pm/issues/I-*.md` | Bug reports |
| `offices/pm/blockers/BL-*.md` | Items blocking progress |
| `offices/pm/tech_debt/TD-*.md` | Known technical debt |
| `offices/pm/archive/` | Completed backlog items and PRDs |

**Key Pattern**: When implementing features, follow TDD:
1. Read the PRD from `offices/pm/prds/` or user stories from `offices/ralph/sprint.json`
2. Write tests first
3. Implement to pass tests
4. Run tests to verify
5. Report completion

## Ralph Autonomous Agent System

Ralph is an autonomous development agent that works through PRDs:

- **Headless contract**: `offices/ralph/prompt.md` - per-iteration instructions injected by ralph.sh
- **Interactive context**: `offices/ralph/CLAUDE.md` - architecture, knowledge index (loaded by `/init-ralph`)
- **PRD**: `offices/ralph/sprint.json` - Current user stories (US- prefixed)
- **State**: `offices/ralph/ralph_agents.json` - Agent assignment + per-session close notes
- **Progress**: `offices/ralph/progress.txt` - Rolling session log
- **Launcher**: `offices/ralph/ralph.sh` - Entry point with iteration control

**How Ralph Works**:
1. Reads `offices/ralph/prompt.md` for per-iteration instructions
2. Selects highest priority `pending` user story from `offices/ralph/sprint.json`
3. Writes tests first (TDD)
4. Implements solution following `specs/standards.md`
5. Runs tests to verify
6. Updates sprint.json with completed status and notes
7. Signals completion with `<promise>COMPLETE</promise>` or `<promise>HUMAN_INTERVENTION_REQUIRED</promise>`

## Testing Standards

### Test Structure (AAA Pattern)
```python
def test_functionName_scenario_expectedResult():
    """
    Given: preconditions
    When: action taken
    Then: expected outcome
    """
    # Arrange
    input = {"id": 1}
    processor = Processor()

    # Act
    result = processor.process(input)

    # Assert
    assert result is True
```

### Coverage Requirements
- Minimum 80% overall coverage (enforced in pyproject.toml)
- 100% coverage for critical paths
- Use pytest fixtures from `tests/conftest.py`

### Test Markers
```python
@pytest.mark.slow          # Slow tests (skip with -m "not slow")
@pytest.mark.integration   # Integration tests
@pytest.mark.unit          # Unit tests
```

## Windows Compatibility Notes

This project runs on Windows (MINGW64_NT). Key considerations:

- CSV files: Always use `newline=''` parameter when opening
- Path handling: Use `os.path.join()` or `pathlib.Path` for cross-platform compatibility
- Line endings: Git handles CRLF/LF conversion automatically

## Tool Configuration

All tools configured in `pyproject.toml`:
- **Black**: 100 char line length, Python 3.11 target
- **Ruff**: Pycodestyle, Pyflakes, isort, flake8-bugbear
- **MyPy**: Strict type checking, untyped defs disallowed
- **Pytest**: Coverage reports, test markers, filterwarnings
- **Coverage**: 80% minimum, branch coverage enabled

## Important Notes for Claude

1. **Always read before modifying**: Read existing code to understand patterns
2. **Follow established patterns**: Especially in `src/common/` - these are the foundation
3. **Test after changes**: Run `pytest tests/` before marking tasks complete
4. **Update PRD**: Mark user stories complete in `offices/ralph/sprint.json` when done
5. **Reference specs**: `specs/standards.md` for conventions, `specs/anti-patterns.md` for what to avoid
6. **Configuration validation**: Run `python validate_config.py` after config changes
7. **No magic numbers**: All values belong in config or as named constants
8. **Error handling**: Use the 5-tier classification system, never silent failures
9. **TDD approach**: Write tests first, then implementation

## Quick Reference

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Development cycle
make pre-commit              # Quality + tests
python validate_config.py    # Validate config
python src/pi/main.py        # Run Pi app
python src/pi/main.py --simulate --dry-run   # Run Pi app in simulator mode

# Autonomous development
./offices/ralph/ralph.sh 10         # Run Ralph for 10 iterations
```
