# Anti-Patterns

## Overview

This document catalogs common mistakes, bad practices, and failure modes encountered in this project. Learn from these to avoid repeating them.

**Last Updated**: 2026-05-03

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

### Using `or` Instead of `is not None`

**Problem**: Using `x or default` when empty string is a valid value.

**Why It's Bad**: Empty string is falsy in Python, so `'' or 'default'` returns `'default'` instead of `''`.

**Solution**: Use explicit `is not None` check when empty string is valid.

```python
# BAD - Empty string becomes default
template = customTemplate or defaultTemplate

# GOOD - Only use default when explicitly None
template = customTemplate if customTemplate is not None else defaultTemplate
```

---

## Database Anti-Patterns

### Using :memory: for Persistence Tests

**Problem**: Using SQLite `:memory:` databases for tests that need data persistence, indexes, or foreign key constraints.

**Why It's Bad**: In-memory databases don't persist across connections and may not exhibit all behaviors of file-based databases (indexes, WAL mode, FK constraints).

**Solution**: Use `tempfile.mktemp(suffix='.db')` for tests requiring persistence or complex database features.

```python
# BAD - Data lost when connection closes
db = ObdDatabase(':memory:')

# GOOD - Persistent temp file
import tempfile
dbPath = tempfile.mktemp(suffix='.db')
db = ObdDatabase(dbPath)
# Clean up after test
os.unlink(dbPath)
```

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

### Ignoring Foreign Key Constraints

**Problem**: Inserting records with foreign key values that don't exist in the parent table.

**Why It's Bad**: When foreign key constraints are enabled (as they should be), inserts will fail. Even if disabled, data integrity is compromised.

**Solution**: Ensure parent records exist before inserting child records, or use NULL for optional relationships.

```python
# BAD - profile 'performance' may not exist
cursor.execute("INSERT INTO realtime_data (profile_id) VALUES (?)", ('performance',))

# GOOD - Check existence or use NULL
profileId = profileId if profileExists(profileId) else None
cursor.execute("INSERT INTO realtime_data (profile_id) VALUES (?)", (profileId,))
```

### Expecting Raw sqlite3 Exceptions Through Wrappers

**Problem**: Test expects `sqlite3.IntegrityError` when using database wrapper that catches all sqlite3 errors.

**Why It's Bad**: The database wrapper's `connect()` context manager converts sqlite3.Error to DatabaseConnectionError. Tests expecting raw exceptions fail.

**Solution**: Expect the wrapper exception (DatabaseConnectionError) and check the message for constraint details.

```python
# BAD - Wrapper catches this and re-raises as DatabaseConnectionError
with pytest.raises(sqlite3.IntegrityError):
    db.insertRecord(invalidData)

# GOOD - Expect the wrapper exception
with pytest.raises(DatabaseConnectionError) as exc:
    db.insertRecord(invalidData)
assert "UNIQUE constraint" in str(exc.value)
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

## Platform Anti-Patterns

### Missing CSV newline Parameter on Windows

**Problem**: Opening CSV files without `newline=''` on Windows.

**Why It's Bad**: CSV writer adds `\r\n`, but text mode also adds `\r`, resulting in `\r\r\n` and blank lines in output.

**Solution**: Always use `newline=''` when opening CSV files.

```python
# BAD - Creates extra blank lines on Windows
with open('data.csv', 'w') as f:
    writer = csv.writer(f)

# GOOD - Works correctly on all platforms
with open('data.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
```

### Platform-Specific Path Separators

**Problem**: Using backslashes or hardcoded path separators in code.

**Why It's Bad**: Breaks cross-platform compatibility.

**Solution**: Use `os.path.join()` or `pathlib.Path` for all path operations.

```python
# BAD - Windows-specific
path = 'src\\obd\\config.json'

# GOOD - Cross-platform
path = os.path.join('src', 'obd', 'config.json')
# Or
path = Path('src') / 'obd' / 'config.json'
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

### Mock Theatre (Excessive Mocking)

**Problem**: Tests that mock every dependency and only verify that mocks were called, rather than testing real behavior. Observed pattern: a single test file with 291 tests and 403 mock references testing getters, log messages, and mock-to-mock wiring.

**Why It's Bad**: Tests pass but prove nothing about the real system. A test like `mockDisplay.showWelcomeScreen.assert_called_once()` only proves you wired a mock correctly - not that the welcome screen actually shows. When the entire test suite is mock theatre, you have zero confidence the system works.

**Solution**: Test real behavior with real (or simulated) systems. Use temp SQLite databases, real config files, real file I/O. Reserve mocks only for true external boundaries (hardware, network services).

```python
# BAD - Mock theatre (proves nothing)
def test_start_initializesDatabase(self):
    mockCreateDb = MagicMock()
    mockDb = MagicMock()
    mockCreateDb.return_value = mockDb
    orchestrator._initializeDatabase()
    mockCreateDb.assert_called_once_with(config)
    mockDb.initialize.assert_called_once()

# GOOD - Tests real behavior with evidence
def test_start_createsDatabase_withExpectedTables(self, tmpDb):
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    orchestrator.start()
    with sqlite3.connect(tmpDb) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert 'realtime_data' in {t[0] for t in tables}
    orchestrator.stop()
```

**Scale indicator**: If a test file has more mock references than test functions, it's likely mock theatre.

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

### Environment Variable Pollution Between Tests

**Problem**: Tests set environment variables that affect other tests in the suite.

**Why It's Bad**: Tests pass in isolation but fail when run together. Order-dependent test failures are hard to debug.

**Solution**: Use `cleanEnv` fixture that removes test variables, and include all test variables in the cleanup list.

```python
# BAD - Variable persists to next test
def test_something():
    os.environ['TEST_VAR'] = 'value'
    # Test doesn't clean up

# GOOD - Use fixture with comprehensive cleanup
@pytest.fixture
def cleanEnv():
    vars_to_clean = ['TEST_VAR', 'DB_PASSWORD', 'API_KEY']
    original = {k: os.environ.get(k) for k in vars_to_clean}
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
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

## Polling / Hardware Anti-Patterns

### Log Spam in Polling Loops

**Problem**: Logging at ERROR/WARNING level inside polling loops for known-absent hardware. When hardware is missing (UPS not connected, display not available, etc.), the polling loop logs the same error every cycle.

**Why It's Bad**: Floods logs with noise (52+ identical lines per 35s observed in simulate mode), obscures real application events, and makes debugging impossible.

**Solution**: Use a consecutive error counter. Log first occurrence at WARNING/ERROR, demote to DEBUG after N failures. Optionally back off the poll interval.

```python
# BAD - Fires every 5 seconds when hardware is absent
while not self._stopEvent.is_set():
    try:
        self.pollDevice()
    except DeviceNotFoundError as e:
        logger.warning(f"Device not found: {e}")  # Spams every cycle!
    self._stopEvent.wait(timeout=5.0)

# GOOD - Log once, suppress repeats, optionally back off
consecutiveErrors = 0
while not self._stopEvent.is_set():
    try:
        self.pollDevice()
        if consecutiveErrors > 0:
            logger.info("Device recovered after %d failures", consecutiveErrors)
        consecutiveErrors = 0
    except DeviceNotFoundError as e:
        consecutiveErrors += 1
        if consecutiveErrors == 1:
            logger.warning(f"Device not found: {e}")
        elif consecutiveErrors == 3:
            logger.warning("Device unreachable, suppressing further warnings")
        else:
            logger.debug(f"Device error (repeated): {e}")
        # Optional: back off poll interval after repeated failures
        backoffInterval = min(60.0, self._pollInterval * (2 ** min(consecutiveErrors, 4)))
    self._stopEvent.wait(timeout=backoffInterval if consecutiveErrors >= 3 else self._pollInterval)
```

**Real examples fixed in this project** (I-007):
- `StatusDisplay._refreshLoop`: GL context error every 2s
- `UpsMonitor._pollingLoop`: Device not found every 5s
- `TelemetryLogger.getTelemetry`: UPS telemetry fail every cycle

---

## State Management Anti-Patterns

### Stale Cross-Component State Shared By Reference

**Problem**: Two components share a piece of state (a power source, a sensor reading, a stage enum), but the producer (the component that observes the world) updates its own copy while the consumer (the component that acts on the state) reads a separate, never-refreshed copy. No freshness contract, no callback, no explicit getter — just two views of "the same" state that quietly diverge.

**Why It's Bad**: The bug is invisible at code-review time because each component, in isolation, looks correct: the producer's polling loop logs the right transition; the consumer's tick loop runs and reads its field. The runtime divergence shows up only under conditions you don't synthetically test (a long-running drain, a transient hardware event, a thread interleave). When it bites, it bites hard — silent failures, no exception, no log line that points at the seam.

**The 8-drain saga (Sprints 21–24)**: `PowerDownOrchestrator.tick()` read `power_source` from a stale view while `UpsMonitor._pollingLoop` correctly detected the BATTERY transition. Drains 1–7 hard-crashed at the LiPo dropout knee while every code-side check passed. Sprint 21 added thread-startup hardening (still crashed). Sprint 22 added forensic logging (still crashed; logger now told us *why* — the orchestrator never saw BATTERY). Sprint 23 added tick-internal instrumentation (still crashed; instrumentation isolated the seam). Drain Test 8 named the bug class definitively: 214 ticks, 100 % `reason=power_source!=BATTERY`, 0 stage transitions, 0 `STAGE_*` rows. **Four sprints of investigation, eight hardware drains, one decoupled state-read.** Sprint 24 US-279 shipped the fix via Escape Hatch #3 below.

**Solution**: Any cross-component state shared by reference must adopt one of three escape hatches. Pick the one that fits your call pattern.

**Escape Hatch #1 — TTL Freshness Contract**

The cache carries a write timestamp. The reader checks the age on every read; if stale, it forces a refresh from the producer. Best when the producer is expensive to query and reads are frequent.

```python
# BAD - state shared by reference, no freshness contract
class Orchestrator:
    def __init__(self, upsMonitor: UpsMonitor) -> None:
        self._powerSource = upsMonitor.powerSource  # cached at init, never refreshed
    def tick(self) -> None:
        if self._powerSource != PowerSource.BATTERY:  # stale read; orchestrator silently bails forever
            return

# GOOD - TTL freshness contract
class Orchestrator:
    _STALE_AFTER_SECONDS = 2.0
    def __init__(self, upsMonitor: UpsMonitor) -> None:
        self._upsMonitor = upsMonitor
        self._powerSource: PowerSource | None = None
        self._powerSourceReadAt: float = 0.0
    def tick(self) -> None:
        if time.monotonic() - self._powerSourceReadAt > self._STALE_AFTER_SECONDS:
            self._powerSource = self._upsMonitor.getPowerSource()
            self._powerSourceReadAt = time.monotonic()
        if self._powerSource != PowerSource.BATTERY:
            return
```

**Escape Hatch #2 — Explicit Pull Semantics (Getter)**

The consumer never holds a cached copy at all. Every read goes through a getter on the producer, which returns the producer's live state. Best when the producer's read is cheap (in-memory) and you'd rather not manage a TTL.

```python
# BAD - shared cache field, drift inevitable
class Orchestrator:
    def tick(self) -> None:
        if self._powerSource != PowerSource.BATTERY:  # whose copy? when last set?
            return

# GOOD - explicit pull; producer is single source of truth
class UpsMonitor:
    def getPowerSource(self) -> PowerSource:
        return self._powerSource  # producer's live, polling-loop-maintained value

class Orchestrator:
    def __init__(self, upsMonitor: UpsMonitor) -> None:
        self._upsMonitor = upsMonitor  # never cache; always pull
    def tick(self) -> None:
        if self._upsMonitor.getPowerSource() != PowerSource.BATTERY:
            return
```

**Escape Hatch #3 — Push-With-Acknowledgment (Callback)**

The producer notifies the consumer on every change via a registered callback; the consumer updates its own copy synchronously inside the callback. Strongest pattern when the consumer needs to react to transitions, not just read steady-state. **This is the pattern Sprint 24 US-279 shipped to close the 8-drain saga** (`UpsMonitor.registerSourceChangeCallback` + `Orchestrator._onPowerSourceChange`); the orchestrator's `self._powerSource` becomes single-writer (the callback) + single-reader (`tick()`).

For correctness, the producer must isolate per-callback exceptions (a regressed audit consumer must not starve the polling loop). For high-stakes consumers, add an acknowledgment so missed callbacks raise an alarm rather than silently degrade.

```python
# BAD - producer logs the transition, consumer never sees it
class UpsMonitor:
    def _pollingLoop(self) -> None:
        if self._detectTransition():
            self._powerSource = newSource  # only this object knows

# GOOD - producer fans out to registered callbacks; per-callback isolation
class UpsMonitor:
    def __init__(self) -> None:
        self._sourceChangeCallbacks: list[Callable[[PowerSource], None]] = []
    def registerSourceChangeCallback(self, callback: Callable[[PowerSource], None]) -> None:
        self._sourceChangeCallbacks.append(callback)
    def _invokeSourceChangeCallbacks(self, newSource: PowerSource) -> None:
        for callback in self._sourceChangeCallbacks:
            try:
                callback(newSource)
            except Exception:
                logger.exception("source-change callback raised; continuing")  # never starve the loop

class Orchestrator:
    def __init__(self) -> None:
        self._powerSource: PowerSource | None = None
    def _onPowerSourceChange(self, newSource: PowerSource) -> None:
        self._powerSource = newSource  # single-writer: this callback
    def tick(self) -> None:
        if self._powerSource != PowerSource.BATTERY:  # single-reader: this method
            return
```

**Choosing between the three**: the bug-class is closed by *any* of the three; the choice is ergonomic. Push-with-ack (#3) is strongest when the consumer must react on transition (orchestrator stage advancement, alarm raising). Explicit pull (#2) is simplest when the consumer reads steady-state without needing transition events. TTL freshness (#1) fits when the producer is expensive (network, hardware bus) and you want to bound staleness without a callback infrastructure.

**Detection at code-review time**: any code that reads a sensor value, source enum, or stage from a sibling component's attribute (rather than via a getter, callback, or TTL-checked cache) gets a comment from the reviewer. The hunting protocol lives in `offices/pm/tech_debt/TD-046-stale-state-cross-component.md` — `rg` patterns plus an audit checklist for places this could already exist (`PowerMonitor`, `TelemetryLogger`, drive-detection state). Until that audit ships, treat any cross-component state read as suspicious.

**Cross-references**:
- US-279 (Sprint 24): the canonical Escape Hatch #3 example; closes the 8-drain saga
- TD-046 (`offices/pm/tech_debt/TD-046-stale-state-cross-component.md`): hunting protocol + future audit
- Drain Test 8 forensic CSV (177 rows, 100 % `reason=power_source!=BATTERY`): the empirical signature of this bug class

---

## Adding New Anti-Patterns

When you encounter a new anti-pattern:

1. Add it to the appropriate category (or create a new one)
2. Include: Problem, Why It's Bad, Solution, Example
3. Keep examples concise and clear
4. Update the "Last Updated" date

---

## Module Refactoring Anti-Patterns

### Patching Re-Export Modules in Tests

**Problem**: Using `@patch` on a module that re-exports from a subpackage instead of patching the actual implementation location.

**Why It's Bad**: The patch targets the re-export alias, not where the code actually runs. The test appears to work but doesn't actually mock the dependency.

**Solution**: Always patch the module where the code is actually defined, not the backward-compatibility re-export.

```python
# BAD - Patches the facade module, not the implementation
@patch('obd.ai_analyzer.urllib')
def test_analyze(mockUrllib):
    # obd.ai_analyzer just re-exports from obd.ai.analyzer
    # The actual code runs in obd.ai.analyzer and won't see this patch!

# GOOD - Patches where the code actually lives
@patch('obd.ai.analyzer.urllib')
def test_analyze(mockUrllib):
    # Now the patch affects the actual implementation
```

### Importing from Re-Export in New Code

**Problem**: Importing from the legacy re-export module in new code.

**Why It's Bad**: Creates unnecessary indirection, makes dependencies unclear, and may break if the re-export layer is eventually removed.

**Solution**: Import directly from the subpackage for new code. Re-exports exist for backward compatibility of existing code only.

```python
# BAD - Uses legacy re-export
from obd.data_logger import ObdDataLogger

# GOOD - Direct import from subpackage
from obd.data import ObdDataLogger
```

---

## Hardware/Import Anti-Patterns

### Catching Only ImportError for Hardware Libraries

**Problem**: Only catching `ImportError` when importing hardware libraries like Adafruit.

**Why It's Bad**: Libraries like `adafruit_blinka` raise `NotImplementedError` or `RuntimeError` on non-supported platforms, not `ImportError`.

**Solution**: Catch multiple exception types when importing hardware libraries.

```python
# BAD - Misses other platform errors
try:
    import board
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

# GOOD - Handles all platform variations
try:
    import board
    from adafruit_rgb_display import st7789
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError):
    HARDWARE_AVAILABLE = False
```

### Cross-Module Module Identity (Dual `sys.path` Resolution)

**Problem**: Two different import forms (`from pi.X import Y` and `from src.pi.X import Y`) for the same source file create TWO DISTINCT module objects, each with its own classes / enums / globals. Equality and `isinstance()` comparisons across the boundary always fail.

**Why It's Bad**: This is the V0.24.1 hotfix bug. It hard-crashed the Pi on every one of 9 drain tests across Sprints 21-24. `PowerSource.BATTERY` produced by code under module name `pi.hardware.ups_monitor` is NOT EQUAL to `PowerSource.BATTERY` produced by code under module name `src.pi.hardware.ups_monitor` even though both come from the same source file. Linters, type checkers, and unit tests that import via a single consistent path do not detect the bug — only production with both paths on `sys.path` exercises it. A non-functioning safety system that LOOKS functional in tests is the worst possible failure mode.

**Why it happens**: Production `main.py` adds both `<repo>/` and `<repo>/src/` to `sys.path` (US-203 pattern lets some helper imports use the `src.X` prefix while shorter `X` imports work for everything else). With both directories on `sys.path`, Python's import machinery resolves `from pi.X` against `<repo>/src/` and `from src.pi.X` against `<repo>/` — two different fully-qualified module names point at the same `.py` file, and the file is executed TWICE under TWO different module objects in `sys.modules`.

**Diagnostic technique (verifiable on the live host)**:

```python
import importlib
A = importlib.import_module('pi.hardware.ups_monitor')
B = importlib.import_module('src.pi.hardware.ups_monitor')
print('A is B:', A is B)                              # False is the bug
print('A.PowerSource is B.PowerSource:',
      A.PowerSource is B.PowerSource)                  # False is the bug
print('A.PowerSource.BATTERY == B.PowerSource.BATTERY:',
      A.PowerSource.BATTERY == B.PowerSource.BATTERY)  # False is the bug
```

**Solution (surgical kill -- self-aliasing guard at module load time)**: Register the module under both names in `sys.modules` on first load. Subsequent imports under either name return the same module object.

```python
# At the top of the source file (e.g. src/pi/hardware/ups_monitor.py):
import sys

_PI_NAME = 'pi.hardware.ups_monitor'
_SRC_NAME = 'src.pi.hardware.ups_monitor'
if __name__ in (_PI_NAME, _SRC_NAME):
    _aliasName = _SRC_NAME if __name__ == _PI_NAME else _PI_NAME
    sys.modules.setdefault(_aliasName, sys.modules[__name__])
```

`setdefault` is load-bearing: only the FIRST loader writes the alias, which means downstream imports get the original module without re-execution side effects. The symmetric guard handles both load orders (`pi.X` first or `src.pi.X` first).

**Defense in depth**: pair the self-alias with a boot-time canary that fires a synthetic transition through the production wiring path and asserts the post-state matches what the comparison expects. Any future regression of the dual-import or any signature drift fails the canary at boot rather than at the next safety event.

```python
# At lifecycle wiring time, after registering the orchestrator callback:
def _verifyOrchestratorCallbackWiring(self, upsMonitor, orchestrator):
    from pi.hardware.ups_monitor import PowerSource
    upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)
    if orchestrator._powerSource != PowerSource.BATTERY:
        logger.error(
            "Wiring self-test FAILED: callback chain not propagating. "
            "Likely cause: cross-module enum identity regression."
        )
```

**Why a regression test must use BOTH paths**: A test that imports via a single consistent prefix (e.g. all `from src.pi.X`) cannot catch this bug — only one module object exists in the test runner. The production-equivalent regression test must:

```python
import importlib

# Load orchestrator the way hardware_manager.py does (with `src.` prefix).
_orchestratorMod = importlib.import_module('src.pi.power.orchestrator')
PowerDownOrchestrator = _orchestratorMod.PowerDownOrchestrator

# Load the polling-thread enum the way lifecycle.py does (no prefix).
_upsViaPiPath = importlib.import_module('pi.hardware.ups_monitor')
PowerSourcePi = _upsViaPiPath.PowerSource

# Now exercise the cross-module path explicitly: callback delivers
# PowerSourcePi.BATTERY into an orchestrator whose internal _PS comes
# from src.pi.X. Pre-fix this fails. Post-fix it passes.
orchestrator._onPowerSourceChange(PowerSourcePi.BATTERY)
orchestrator.tick(currentVcell=3.65, currentSource=PowerSourcePi.BATTERY)
assert orchestrator.state == PowerState.WARNING
```

See `tests/pi/regression/test_powersource_module_identity.py` for the canonical example. The test was written to fail RED before the V0.24.1 fix and pass GREEN after.

**Long-term fix**: normalize all imports across the codebase to one consistent prefix (or remove one of the two paths from `sys.path`). The self-aliasing guard is a surgical fix for one critical module; codebase-wide normalization is the structural fix.

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-05-04 | Rex (Ralph) | **V0.24.1 hotfix.** Added "Cross-Module Module Identity (Dual `sys.path` Resolution)" anti-pattern under "Hardware/Import Anti-Patterns" section. Documents the Python module-identity footgun isolated by Drain Test 9 (9-drain saga, Sprints 21–24): a single `.py` file loaded under two distinct module names produces two distinct enum classes that never compare equal across the boundary. Includes the self-aliasing guard pattern (the surgical kill), the boot-time canary pattern (the early-warning regression gate), the cross-module regression-test idiom (`importlib.import_module` under both names), and the live-host diagnostic technique. Cross-links the canonical implementation in `src/pi/hardware/ups_monitor.py` + `tests/pi/regression/test_powersource_module_identity.py` + Drain Test 10 closure record. |
| 2026-05-03 | Rex (Ralph) | **US-281 (Sprint 24).** Added "Stale Cross-Component State Shared By Reference" anti-pattern under new "State Management Anti-Patterns" section. Documents the bug class isolated by Drain Test 8 (8-drain saga, Sprints 21–24) plus three escape hatches (TTL freshness contract / explicit pull via getter / push-with-acknowledgment callback). Cross-links US-279 as the canonical Escape Hatch #3 example and TD-046 for the hunting protocol + future codebase audit. Additive only; no existing sections modified. |
| 2026-02-05 | Tester Agent | Added Mock Theatre anti-pattern: excessive mocking that proves nothing about real system behavior. Based on audit finding 787 mock-heavy tests deleted. |
| 2026-02-01 | Marcus (PM) | Added Polling/Hardware anti-pattern: log spam in polling loops per I-010 |
| 2026-01-22 | Knowledge Update | Added module refactoring anti-patterns (patching re-exports, importing from re-exports) |
| 2026-01-22 | Knowledge Update | Added database wrapper exception expectations, test environment pollution patterns |
| 2026-01-22 | Knowledge Update | Added platform anti-patterns (CSV newline, path separators), database anti-patterns (:memory:, FK constraints), truthiness issues, hardware imports |
| 2026-01-21 | M. Cornelison | Initial anti-patterns document |
