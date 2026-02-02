# Coding Standards

## Overview

This document defines the coding standards, naming conventions, and best practices for the Eclipse OBD-II Performance Monitoring System.

**Last Updated**: 2026-02-01
**Author**: Michael Cornelison

---

## 1. File Header Requirements

### Python Files

Every Python file must include this header:

```python
################################################################################
# File Name: module_name.py
# Purpose/Description: Clear, concise description of module purpose
# Author: Author Name
# Creation Date: YYYY-MM-DD
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# YYYY-MM-DD    | A. Name      | Initial implementation
# ================================================================================
################################################################################
```

### SQL Files

Every SQL file must include this header:

```sql
-- ================================================================================
-- File Name: table_name.sql
-- Purpose/Description: DDL for table_name table
-- Author: Author Name
-- Creation Date: YYYY-MM-DD
-- Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
--
-- Modification History:
-- ================================================================================
-- Date          | Author       | Description
-- ================================================================================
-- YYYY-MM-DD    | A. Name      | Initial implementation
-- ================================================================================
```

---

## 2. Naming Conventions

### Python

| Element | Convention | Example |
|---------|------------|---------|
| Functions | camelCase | `getUserData()`, `processRecords()` |
| Variables | camelCase | `recordCount`, `isValid` |
| Classes | PascalCase | `ConfigValidator`, `DataProcessor` |
| Constants | UPPER_SNAKE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Modules | snake_case | `config_validator.py`, `error_handler.py` |
| Private | _prefix | `_internalMethod()`, `_privateVar` |

**Correct Examples**:
```python
# Functions and variables: camelCase
def getContentConfig():
    userCount = 0
    apiEndpoint = "https://api.example.com"
    return loadConfig()

# Classes: PascalCase
class ConfigValidator:
    pass

# Constants: UPPER_SNAKE_CASE
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
```

**Incorrect Examples**:
```python
# Wrong: PascalCase for function
def GetContentConfig():  # Should be getContentConfig

# Wrong: snake_case for function
def get_content_config():  # Should be getContentConfig

# Wrong: PascalCase for variable
UserCount = 0  # Should be userCount
```

### SQL (Database Objects)

| Element | Convention | Example |
|---------|------------|---------|
| Tables | snake_case | `user_accounts`, `realtime_data` |
| Columns | snake_case | `created_at`, `is_active`, `profile_id` |
| Primary Keys | table_id | `user_id`, `session_id` |
| Foreign Keys | FK_child_parent | `FK_realtime_profile` |
| Indexes | IX_table_column | `IX_realtime_timestamp` |
| Procedures | sp_action_noun | `sp_get_statistics` |

**Correct Examples**:
```sql
CREATE TABLE realtime_data (
    realtime_data_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    profile_id INTEGER REFERENCES profiles(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IX_realtime_data_timestamp ON realtime_data(timestamp);
CREATE INDEX IX_realtime_data_profile ON realtime_data(profile_id);
```

**Incorrect Examples**:
```sql
-- Wrong: PascalCase or camelCase
CREATE TABLE RealtimeData (    -- Should be realtime_data
    RealtimeDataId INTEGER,     -- Should be realtime_data_id
    parameterName TEXT          -- Should be parameter_name
);
```

---

## 3. Code Commenting Standards

### When to Comment

**DO Comment**:
- Complex business logic
- Non-obvious algorithms
- Workarounds for known issues
- External dependencies
- Magic numbers (explain why)
- API quirks or undocumented behavior

**DON'T Comment**:
- Self-explanatory code
- Every line or function
- Obvious operations
- Code that should be refactored instead

### Comment Examples

**Good Comments**:
```python
# Divide by 1000 because API returns milliseconds, we need seconds
durationSeconds = responseTimeMs / 1000

# Rate limit: API allows max 60 requests/minute
# Using 50 to leave buffer for retries
requestsPerMinute = 50

# Workaround for OBD-II dongle returning null for unsupported PIDs
# Some 1998 vehicles don't support all standard PIDs
items = response.get('items') or []

# Use regex pattern to match both ${VAR} and ${VAR:default} syntax
# Group 1 = variable name, Group 2 = optional default value
pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
```

**Bad Comments**:
```python
# Initialize count to 0
count = 0  # Obvious, don't comment

# Get the user
user = getUser(id)  # Obvious, don't comment

# Loop through items
for item in items:  # Obvious, don't comment
    pass
```

---

## 4. Python Coding Standards

### General

- Follow PEP 8 style guide (with camelCase exception for functions/variables)
- Maximum line length: 100 characters
- Use 4 spaces for indentation (no tabs)
- Use type hints for function parameters and returns

### Imports

Order imports as:
1. Standard library
2. Third-party packages
3. Local modules

```python
# Standard library
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

# Third-party
import pytest
from unittest.mock import MagicMock, patch

# Local
from common.config_validator import ConfigValidator
from common.logging_config import getLogger, setupLogging
from common.error_handler import RetryableError, classifyError
```

### Type Hints

```python
def processRecords(
    records: List[Dict[str, Any]],
    config: Dict[str, Any],
    dryRun: bool = False
) -> Tuple[bool, int, str]:
    """
    Process a list of records.

    Args:
        records: List of record dictionaries
        config: Configuration dictionary
        dryRun: If True, don't persist changes

    Returns:
        Tuple of (success, recordCount, errorMessage)
    """
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def functionName(param1: str, param2: int = 0) -> bool:
    """
    Brief one-line description.

    Longer description if needed, explaining the function's
    purpose and any important details.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter with default

    Returns:
        Description of return value

    Raises:
        ValueError: If param1 is empty
        ConnectionError: If database unavailable

    Example:
        >>> functionName("test", 42)
        True
    """
    pass
```

### Error Handling

```python
# Good: Specific exception handling with classification
try:
    result = apiClient.fetchData(endpoint)
except requests.Timeout:
    logger.warning(f"Timeout fetching {endpoint}, will retry")
    raise RetryableError(f"Timeout: {endpoint}")
except requests.HTTPError as e:
    if e.response.status_code == 401:
        raise AuthenticationError("Invalid credentials")
    raise

# Bad: Catching all exceptions
try:
    result = apiClient.fetchData(endpoint)
except Exception:  # Too broad
    pass  # Silent failure - NEVER do this
```

---

## 5. SQL Coding Standards

### General

- Keywords in UPPERCASE
- Identifiers in snake_case
- Use 4 spaces for indentation
- One column per line in SELECT
- Explicit column lists (no SELECT *)
- Use WAL mode for SQLite

### SELECT Statements

```sql
SELECT
    rd.realtime_data_id,
    rd.timestamp,
    rd.parameter_name,
    rd.value,
    rd.unit,
    p.name AS profile_name
FROM
    realtime_data AS rd
    LEFT JOIN profiles AS p ON rd.profile_id = p.id
WHERE
    rd.profile_id = ?
    AND rd.timestamp >= ?
ORDER BY
    rd.timestamp DESC
LIMIT 1000;
```

### CREATE TABLE

```sql
CREATE TABLE IF NOT EXISTS statistics (
    -- Primary key
    statistics_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Business columns
    parameter_name TEXT NOT NULL,
    analysis_date DATETIME NOT NULL,
    profile_id INTEGER NOT NULL,
    max_value REAL,
    min_value REAL,
    avg_value REAL,
    mode_value REAL,
    std_1 REAL,
    std_2 REAL,
    outlier_min REAL,
    outlier_max REAL,

    -- Audit columns
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_statistics_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS IX_statistics_analysis_date
    ON statistics(analysis_date);
CREATE INDEX IF NOT EXISTS IX_statistics_profile
    ON statistics(profile_id);
```

---

## 6. Configuration Standards

### config.json Structure

```json
{
    "application": {
        "name": "Eclipse OBD-II Monitor",
        "version": "1.0.0",
        "environment": "${APP_ENVIRONMENT:development}"
    },
    "database": {
        "path": "${DB_PATH:./data/obd2.db}",
        "walMode": true,
        "timeout": 30
    },
    "api": {
        "baseUrl": "${API_BASE_URL}",
        "auth": {
            "clientId": "${API_CLIENT_ID}",
            "clientSecret": "${API_CLIENT_SECRET}"
        },
        "retry": {
            "maxRetries": 3,
            "retryDelayMs": 1000,
            "retryBackoffMultiplier": 2.0
        }
    },
    "logging": {
        "level": "${LOG_LEVEL:INFO}",
        "maskPII": true
    }
}
```

### Environment Variables

Use descriptive, prefixed names:

```bash
# Application
APP_ENVIRONMENT=development

# Database
DB_PATH=./data/obd2.db

# API
API_BASE_URL=https://vpic.nhtsa.dot.gov/api
API_CLIENT_ID=your_client_id
API_CLIENT_SECRET=your_secret

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/obd2.log

# OBD-II (future)
OBD_BLUETOOTH_MAC=00:00:00:00:00:00
OBD_POLLING_INTERVAL_MS=1000
```

---

## 7. Testing Standards

### Test File Naming

- Mirror source structure: `src/common/config_validator.py` → `tests/test_config_validator.py`
- Use `test_` prefix

### Test Function Naming

```python
def test_functionName_scenario_expectedResult():
    """
    Given: preconditions
    When: action taken
    Then: expected outcome
    """
    pass

# Examples
def test_loadConfig_validFile_returnsDict():
    pass

def test_loadConfig_missingFile_raisesFileNotFound():
    pass

def test_validateEmail_invalidFormat_returnsFalse():
    pass
```

### Test Structure (AAA Pattern)

```python
def test_processRecord_validRecord_returnsTrue():
    """
    Given: A valid record with required fields
    When: processRecord is called
    Then: Returns True and increments processed count
    """
    # Arrange
    record = {"id": 1, "name": "Test"}
    processor = RecordProcessor()

    # Act
    result = processor.process(record)

    # Assert
    assert result is True
    assert processor.processedCount == 1
```

### Fixtures

```python
# conftest.py
import pytest

@pytest.fixture
def sampleConfig():
    """Provide sample configuration for tests."""
    return {
        "database": {"path": ":memory:"},
        "api": {"baseUrl": "https://test.api.com"}
    }

@pytest.fixture
def mockApiClient(mocker):
    """Provide mocked API client."""
    mock = mocker.patch('src.clients.api_client.ApiClient')
    mock.return_value.fetch.return_value = {"data": []}
    return mock
```

### Test Markers

```python
@pytest.mark.slow          # Skip with -m "not slow"
@pytest.mark.integration   # Integration tests
@pytest.mark.unit          # Unit tests
```

---

## 8. Logging Standards

### Log Message Format

```python
# Good: Contextual information
logger.info(f"Processing batch | batchId={batchId} | recordCount={len(records)}")
logger.error(f"Failed to fetch | endpoint={endpoint} | status={response.status_code}")

# Bad: Vague messages
logger.info("Processing")  # What? How many?
logger.error("Failed")  # Why? What failed?
```

### Structured Logging

```python
# Using logWithContext for structured data
logWithContext(logger, logging.INFO, "Batch completed",
               batchId=batchId,
               recordCount=recordCount,
               durationMs=durationMs,
               status="success")
```

### Sensitive Data

```python
# Never log passwords or tokens
logger.debug(f"Authenticating user={username}")  # OK
logger.debug(f"Password={password}")  # NEVER

# Use maskSecret for sensitive values
from common.secrets_loader import maskSecret
logger.debug(f"API key: {maskSecret(apiKey)}")  # Shows "apik***"
```

---

## 9. Git Standards

### Commit Messages

```
<type>: <short description (50 chars)>

<body: what and why, wrap at 72 chars>

Task: #<task-id>
Co-Authored-By: Claude <noreply@anthropic.com>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code change that neither fixes nor adds
- `test`: Adding tests
- `docs`: Documentation only
- `chore`: Maintenance tasks

### Branch Names

```
feature/8-add-documentation
bugfix/56-fix-timeout-handling
hotfix/critical-security-patch
ralph/eclipse-obd-ii
```

---

## 10. Code Review Checklist

Before submitting for review:

- [ ] Code follows naming conventions (camelCase functions, PascalCase classes)
- [ ] File headers are present and correct
- [ ] Functions have type hints and docstrings
- [ ] Tests are included and passing (80% minimum coverage)
- [ ] No hardcoded values (use config)
- [ ] Errors are handled appropriately (5-tier classification)
- [ ] Logging is sufficient but not excessive (with PII masking)
- [ ] No security vulnerabilities
- [ ] No unnecessary complexity
- [ ] Documentation updated if needed

---

## 11. Project-Specific Patterns

### ConfigValidator

Use dot-notation for nested key access:
```python
DEFAULTS = {
    'database.timeout': 30,
    'api.retry.maxRetries': 3
}
```

### SecretsLoader

Regex pattern for placeholder resolution:
```python
# Matches ${VAR} and ${VAR:default}
pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
```

loadEnvFile() does NOT override existing environment variables.

### PIIMaskingFilter

Automatically masks:
- Email: `[EMAIL_MASKED]`
- Phone (555-123-4567, 555.123.4567, 5551234567): `[PHONE_MASKED]`
- SSN (123-45-6789): `[SSN_MASKED]`

### Error Classification

```python
from common.error_handler import ErrorCategory, classifyError

# Auto-classification based on error type and message
category = classifyError(error)
# Returns: RETRYABLE, AUTHENTICATION, CONFIGURATION, DATA, or SYSTEM
```

### Retry Decorator

```python
from common.error_handler import retry, RetryableError

@retry(maxRetries=3, initialDelay=1.0, backoffMultiplier=2.0)
def fetchData():
    # Implementation
    pass
```

---

## 12. Code Organization Rules

### Rule 1: Write Reusable Code

All code should be written with reusability in mind. Extract common logic into shared utilities, use parameterized functions instead of hardcoded behavior, and design interfaces that can serve multiple callers. Before writing new code, check if existing utilities in `src/common/` or domain-specific helpers already provide the needed functionality.

### Rule 2: Keep Files Small

Files should remain focused and manageable:

- **Source files**: Target ~300 lines. Consider splitting when exceeding this.
- **Test files**: Target ~500 lines. Consider splitting by test category when exceeding this.

Large files are harder to navigate, review, test, and work with in AI-assisted development (context window limits). When splitting, preserve the public API via re-exports in `__init__.py` to avoid breaking imports.

### Rule 3: Organize by Functionality and Module

Group related functionality into packages/subpackages. Within each package, follow the established structure:

```
src/<domain>/<package>/
├── types.py         # Enums, dataclasses, constants (zero project dependencies)
├── exceptions.py    # Custom exceptions
├── <core>.py        # Main class implementation
├── helpers.py       # Factory functions, config utilities
└── __init__.py      # Public API exports
```

`types.py` must have no dependencies on other project modules to prevent circular imports. Use `TYPE_CHECKING` for type hints that would otherwise create runtime circular dependencies.

---

## 13. Database Coding Patterns

### Always Use ObdDatabase.connect()

Never use raw `sqlite3.connect()`. The `ObdDatabase.connect()` context manager sets required PRAGMAs (`foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`) on every connection. Raw connections will NOT have these set.

```python
# BAD - PRAGMAs not set, FK constraints not enforced
conn = sqlite3.connect('data/obd.db')

# GOOD - PRAGMAs set automatically
with db.connect() as conn:
    conn.execute("INSERT INTO ...")
```

### ObdDatabase.initialize() Is Idempotent

Uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. Safe to run on populated databases -- will not destroy existing data. Always call before first use.

### No close() Method

`ObdDatabase` uses context managers for connections. The database object itself doesn't hold open connections and doesn't need explicit closing.

### Adding New Indexes

New indexes must be added to the `ALL_INDEXES` list in `src/obd/database.py` to be created automatically on `initialize()`. Use the naming convention `IX_tablename_column`.

### FK Constraint Awareness

- FK constraints use `ON DELETE SET NULL` or `ON DELETE CASCADE` -- check the schema before inserting rows with `profile_id` references
- `connection_log`, `battery_log`, and `power_log` have no FK constraints (hardware telemetry is profile-independent)
- Always ensure parent records exist before inserting child records, or use NULL for optional relationships

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-21 | M. Cornelison | Updated standards for Eclipse OBD-II project with project-specific patterns |
| 2026-01-29 | Marcus (PM) | Added Section 12: Code Organization Rules (reusability, file size limits, package structure) per I-001 |
| 2026-02-01 | Marcus (PM) | Added Section 13: Database Coding Patterns per I-010 (ObdDatabase usage, idempotent init, indexes, FKs) |
