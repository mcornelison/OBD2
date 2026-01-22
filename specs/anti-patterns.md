# Anti-Patterns

## Overview

This document catalogs common mistakes, bad practices, and failure modes encountered in this project. Learn from these to avoid repeating them.

**Last Updated**: [Date]

---

## How to Use This Document

Each anti-pattern includes:
- **Problem**: What went wrong
- **Why It's Bad**: The consequences
- **Solution**: The correct approach
- **Example**: Code showing bad vs. good

When you encounter a new anti-pattern, add it here to help future developers.

---

## Configuration Anti-Patterns

### Hardcoded Secrets

**Problem**: Embedding credentials directly in code or config files committed to git.

**Why It's Bad**: Secrets get exposed in version control history, even if later removed.

**Solution**: Use environment variables with `${VAR_NAME}` placeholders in config.json.

```python
# BAD
password = "my_secret_password"
config = {"api_key": "abc123xyz"}

# GOOD
password = os.environ.get("DB_PASSWORD")
config = {"api_key": "${API_KEY}"}  # Resolved at runtime
```

### Magic Numbers

**Problem**: Using unexplained numeric values directly in code.

**Why It's Bad**: Hard to understand, maintain, and modify.

**Solution**: Use named constants or configuration values.

```python
# BAD
time.sleep(30)
if retries > 3:
    raise Exception("Failed")

# GOOD
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

time.sleep(TIMEOUT_SECONDS)
if retries > MAX_RETRIES:
    raise Exception("Failed")
```

---

## Error Handling Anti-Patterns

### Silent Failures

**Problem**: Catching exceptions without logging or re-raising.

**Why It's Bad**: Errors go unnoticed, causing mysterious failures later.

**Solution**: Always log errors, even if you handle them gracefully.

```python
# BAD
try:
    result = api_call()
except Exception:
    pass  # Silent failure!

# GOOD
try:
    result = api_call()
except Exception as e:
    logger.error(f"API call failed: {e}")
    raise  # Or handle appropriately
```

### Catching Too Broadly

**Problem**: Using bare `except:` or `except Exception:` everywhere.

**Why It's Bad**: Masks unexpected errors, makes debugging difficult.

**Solution**: Catch specific exceptions you can handle.

```python
# BAD
try:
    data = fetch_data()
except Exception:
    return None

# GOOD
try:
    data = fetch_data()
except requests.Timeout:
    logger.warning("Request timed out, will retry")
    raise RetryableError("Timeout")
except requests.HTTPError as e:
    if e.response.status_code == 404:
        return None
    raise
```

### Retry Without Backoff

**Problem**: Retrying failed operations immediately in a tight loop.

**Why It's Bad**: Overwhelms the failing service, wastes resources, often makes things worse.

**Solution**: Use exponential backoff between retries.

```python
# BAD
for i in range(5):
    try:
        return api_call()
    except Exception:
        continue  # Immediate retry!

# GOOD
delays = [1, 2, 4, 8, 16]
for i, delay in enumerate(delays):
    try:
        return api_call()
    except RetryableError:
        if i < len(delays) - 1:
            time.sleep(delay)
        else:
            raise
```

---

## Database Anti-Patterns

### SELECT *

**Problem**: Using `SELECT *` instead of specifying columns.

**Why It's Bad**: Returns unnecessary data, breaks when schema changes, poor performance.

**Solution**: Always specify the columns you need.

```sql
-- BAD
SELECT * FROM users WHERE active = 1;

-- GOOD
SELECT user_id, email, created_at
FROM users
WHERE active = 1;
```

### Missing Indexes

**Problem**: Querying large tables without appropriate indexes.

**Why It's Bad**: Full table scans, slow queries, database load.

**Solution**: Add indexes for columns used in WHERE, JOIN, and ORDER BY clauses.

```sql
-- If you frequently query by email:
CREATE INDEX IX_users_email ON users(email);

-- If you frequently filter by status and date:
CREATE INDEX IX_orders_status_date ON orders(status, created_at);
```

### N+1 Queries

**Problem**: Fetching related data in a loop, one query per item.

**Why It's Bad**: Multiplies database round-trips, extremely slow at scale.

**Solution**: Use JOINs or batch fetching.

```python
# BAD - N+1 queries
users = db.query("SELECT * FROM users")
for user in users:
    orders = db.query(f"SELECT * FROM orders WHERE user_id = {user.id}")

# GOOD - Single query with JOIN
query = """
    SELECT u.*, o.*
    FROM users u
    LEFT JOIN orders o ON u.id = o.user_id
"""
results = db.query(query)
```

---

## Code Organization Anti-Patterns

### God Functions

**Problem**: Functions that do too many things, hundreds of lines long.

**Why It's Bad**: Hard to test, understand, and maintain.

**Solution**: Break into smaller, focused functions with single responsibilities.

```python
# BAD
def process_order(order):
    # 200 lines doing validation, calculation,
    # database updates, email sending, logging...

# GOOD
def process_order(order):
    validate_order(order)
    total = calculate_total(order)
    save_order(order, total)
    send_confirmation(order)
```

### Premature Abstraction

**Problem**: Creating abstractions before you have multiple use cases.

**Why It's Bad**: Wrong abstractions are worse than duplication. You can't predict future needs.

**Solution**: Wait until you have 2-3 concrete examples before abstracting.

```python
# BAD - Abstracting too early
class AbstractDataProcessor:
    def preProcess(self): pass
    def process(self): pass
    def postProcess(self): pass
    def validate(self): pass
    # ... when you only have one processor

# GOOD - Start concrete
def process_user_data(data):
    # Just write the code you need
    # Abstract later when patterns emerge
```

### Copy-Paste Programming

**Problem**: Duplicating code blocks instead of extracting shared logic.

**Why It's Bad**: Bugs must be fixed in multiple places, inconsistencies creep in.

**Solution**: Extract common code into functions (but don't over-abstract).

```python
# BAD - Same validation in multiple places
def create_user(data):
    if not data.get('email') or '@' not in data['email']:
        raise ValueError("Invalid email")
    # ...

def update_user(data):
    if not data.get('email') or '@' not in data['email']:
        raise ValueError("Invalid email")
    # ...

# GOOD - Extracted validation
def validate_email(email):
    if not email or '@' not in email:
        raise ValueError("Invalid email")

def create_user(data):
    validate_email(data.get('email'))
    # ...
```

---

## Testing Anti-Patterns

### Testing Implementation Details

**Problem**: Tests that break when internal code changes, even if behavior is correct.

**Why It's Bad**: Makes refactoring painful, tests become a burden.

**Solution**: Test behavior and outputs, not internal implementation.

```python
# BAD - Testing implementation
def test_user_service():
    service = UserService()
    service.process()
    assert service._internal_cache == {...}  # Testing private state!

# GOOD - Testing behavior
def test_user_service():
    service = UserService()
    result = service.process()
    assert result.success is True
    assert result.user_count == 5
```

### No Assertions

**Problem**: Tests that run code but don't verify anything.

**Why It's Bad**: Tests pass even when code is broken.

**Solution**: Every test must have meaningful assertions.

```python
# BAD - No assertion
def test_create_user():
    user = create_user({"name": "Test"})
    # Test passes but verifies nothing!

# GOOD - Meaningful assertions
def test_create_user():
    user = create_user({"name": "Test"})
    assert user is not None
    assert user.name == "Test"
    assert user.id is not None
```

---

## Logging Anti-Patterns

### Logging Sensitive Data

**Problem**: Including passwords, tokens, or PII in log messages.

**Why It's Bad**: Security breach, compliance violations.

**Solution**: Never log secrets. Mask PII.

```python
# BAD
logger.info(f"User login: {username}, password: {password}")
logger.debug(f"API response: {response.json()}")  # May contain secrets!

# GOOD
logger.info(f"User login: {username}")
logger.debug(f"API response status: {response.status_code}")
```

### Logging in Loops

**Problem**: Writing log entries inside tight loops.

**Why It's Bad**: Floods logs, kills performance, makes important messages hard to find.

**Solution**: Log summaries, or use sampling/batching.

```python
# BAD
for record in million_records:
    logger.info(f"Processing record {record.id}")
    process(record)

# GOOD
logger.info(f"Processing {len(records)} records")
for record in records:
    process(record)
logger.info(f"Completed processing {len(records)} records")
```

---

## Adding New Anti-Patterns

When you encounter a new anti-pattern:

1. Add it to the appropriate category (or create a new one)
2. Include: Problem, Why It's Bad, Solution, Example
3. Keep examples concise and clear
4. Update the "Last Updated" date

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| [Date] | [Name] | Initial anti-patterns document |
