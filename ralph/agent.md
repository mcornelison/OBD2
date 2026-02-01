# Ralph Autonomous Agent Instructions

## Overview

You are Ralph, an autonomous development agent. Your role is to work through the project backlog systematically, implementing tasks according to the defined standards and methodology.

## Core Principles

1. **Follow the Stories**: Work from `ralph/stories.json` to select and complete user stories (US- prefixed)
2. **Follow Standards**: All code must adhere to `specs/standards.md`
3. **Test-Driven Development**: Write tests before implementation
4. **Incremental Progress**: Complete one task fully before starting the next
5. **Document Everything**: Update backlog and notes as you work

## Workflow

### 1. Task Selection

Select the next user story using these criteria:
1. Choose the highest priority `pending` story from `ralph/stories.json`
2. Ensure all dependencies are met (check `status` of prerequisite stories)
3. Mark the selected story as `in_progress`

### 2. Task Execution

For each task:

```
1. Read the task description and steps
2. Understand the testing criteria
3. Write tests first (TDD)
4. Implement the solution
5. Run tests to verify
6. Update documentation if needed
7. Mark task as `completed` with date
```

### 3. Task Completion

When completing a user story:
1. Run all relevant tests
2. Verify tests pass
3. Update `ralph/stories.json`:
   - Set `status: "completed"`
   - Set `passed: true` (if tests pass)
   - Set `completedDate` to current date
   - Add any notes about the implementation

## Coding Standards

### File Headers

Every file must include the standard header from `specs/standards.md`.

### Naming Conventions

- **Python functions/variables**: camelCase
- **Python classes**: PascalCase
- **SQL tables/columns**: snake_case
- **Constants**: UPPER_SNAKE_CASE

### Code Quality Rules

- **Reusable code**: Write functions and classes that can be reused across the codebase. Avoid duplicating logic -- extract shared patterns into common utilities.
- **Small files**: Keep source files under ~300 lines and test files under ~500 lines. If a file exceeds this, split it into focused modules (see `specs/anti-patterns.md`).
- **Organized structure**: Follow the established subpackage pattern (`types.py`, `exceptions.py`, core modules, `helpers.py`). Group related functionality together.
- **Single responsibility**: Each module/class does one thing well. Don't combine unrelated functionality.

### Documentation

- Public functions require docstrings
- Complex logic requires inline comments
- Update README when adding features

## Error Handling

Follow the error classification from `specs/methodology.md`:
- Retryable errors: Use exponential backoff
- Configuration errors: Fail fast with clear message
- Data errors: Log and continue/skip
- System errors: Fail with diagnostics

## Testing Requirements

- Minimum 80% code coverage
- 100% coverage for critical paths
- Use pytest fixtures from `tests/conftest.py`
- Follow AAA pattern (Arrange, Act, Assert)

## Communication

### Progress Updates

After each task, provide a summary:
```
Task #[ID]: [Title]
Status: [completed/blocked/in_progress]
Changes:
- [List of files modified]
Notes:
- [Any important observations]
```

### Blocking Issues

If blocked, document:
1. What is blocking
2. What was tried
3. Suggested resolution

## Files to Reference

| File | Purpose |
|------|---------|
| `ralph/stories.json` | Current user stories and status |
| `specs/standards.md` | Coding conventions |
| `specs/methodology.md` | Development processes |
| `specs/architecture.md` | System design |
| `specs/glossary.md` | Domain terminology |
| `specs/anti-patterns.md` | Common mistakes to avoid |
| `pm/roadmap.md` | Project roadmap and phases |
| `CLAUDE.md` | Project context |

## Commands

### Running Tests
```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=html
```

### Validating Configuration
```bash
python validate_config.py
```

### Running the Application
```bash
python src/main.py --help
python src/main.py --dry-run
```

## Safety Guidelines

1. **Never commit secrets** - Use environment variables
2. **Never force push** - Especially to main/master
3. **Always run tests** - Before marking tasks complete
4. **Backup before major changes** - Create branches
5. **Ask when uncertain** - If requirements are unclear

## Session Persistence

Progress is tracked in:
- `ralph/stories.json` - User story status
- `ralph/progress.txt` - Session notes
- `ralph/ralph_agents.json` - Agent state

At the end of each session, update these files to preserve context for the next session.

---

## Operational Tips and Tricks

This section contains practical learnings from project implementation. For definitions, see `specs/glossary.md`. For anti-patterns to avoid, see `specs/anti-patterns.md`.

### Mocking and Testing

**Placeholder names for unavailable dependencies**
When a dependency like scapy may not be available, define placeholder names in the except block so tests can mock them:
```python
try:
    from scapy.all import sniff, get_if_list
except ImportError:
    sniff = None
    get_if_list = None
```

**Capturing stdout/stderr in tests**
Use pytest's `capsys` fixture to capture and verify console output:
```python
def test_prints_warning(capsys):
    printWarning()
    captured = capsys.readouterr()
    assert "Warning:" in captured.out
```

**Mocking classes vs instances**
When mocking a class, use `@patch('module.ClassName')` and set `.return_value` for instance method behavior:
```python
@patch('src.common.blocklist_fetcher.BlocklistFetcher')
def test_load(mockFetcherClass):
    mockInstance = MagicMock()
    mockFetcherClass.return_value = mockInstance
    mockInstance.fetchAllSources.return_value = {'source': ['domain.com']}
```

**Testing argparse --help**
Use `pytest.raises(SystemExit)` since argparse calls `sys.exit(0)` for --help:
```python
def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        parseArguments(['--help'])
    assert exc.value.code == 0
```

### Windows-Specific

**CSV file handling**
Always use `newline=''` parameter when opening CSV files to prevent extra blank lines on Windows. See `specs/anti-patterns.md` for details.

**Path handling in tests**
Use `os.path.join()` for path assertions to work on both Windows and Unix. See `specs/anti-patterns.md` for details.

### scapy/Npcap

**scapy import can fail multiple ways**
Catch both ImportError and runtime errors when importing scapy:
```python
try:
    from scapy.all import sniff, get_if_list, IP, TCP, UDP
    SCAPY_AVAILABLE = True
except (ImportError, OSError) as e:
    SCAPY_AVAILABLE = False
```

**Npcap detection**
`get_if_list()` may return an empty list even when scapy imports successfully. Always check for Npcap availability separately:
```python
def isNpcapInstalled() -> bool:
    if not SCAPY_AVAILABLE:
        return False
    try:
        interfaces = get_if_list()
        return len(interfaces) > 0
    except Exception:
        return False
```

### Threading Patterns

**Timer threads for background tasks**
Use `threading.Timer` with `daemon=True` for non-blocking cleanup:
```python
timer = threading.Timer(interval, callback)
timer.daemon = True  # Won't block application exit
timer.start()
```

**Thread-safe caching**
Use `threading.Lock` around all dictionary modifications in shared caches:
```python
self._lock = threading.Lock()

def set(self, key, value):
    with self._lock:
        self._cache[key] = value
```

**Clean thread interruption**
Use threading.Event.wait(timeout) instead of time.sleep for clean shutdown:
```python
self._stopEvent = threading.Event()

def _pollLoop(self):
    while not self._stopEvent.is_set():
        self._doWork()
        self._stopEvent.wait(timeout=self._interval)  # Interruptible sleep

def stop(self):
    self._stopEvent.set()  # Immediately wakes the thread
```

**Exception-safe polling callbacks**
Catch exceptions in polling loops to prevent thread crash:
```python
def _pollLoop(self):
    while self._running:
        try:
            data = self._readData()
            if self._callback:
                self._callback(data)  # May raise
        except Exception as e:
            self._logger.error(f"Polling error: {e}")
        time.sleep(self._interval)
```

### DNS and Network

**socket.gethostbyaddr() exceptions**
Catch multiple exception types for reverse DNS:
```python
try:
    hostname, aliases, addresses = socket.gethostbyaddr(ip)
    return hostname
except (socket.herror, socket.gaierror, socket.timeout):
    return None
```

**Cache DNS failures**
Cache failed lookups as None to avoid repeated queries for unresolvable IPs:
```python
hostname = resolveHostname(ip)  # Returns None on failure
cache.set(ip, hostname)  # Cache None too
```

### Configuration

**Dot-notation key mapping for defaults**
Apply defaults via dot-notation paths for nested config:
```python
DEFAULTS = {
    'adServerSources.updateIntervalHours': 24,
    'monitoring.connectionIdleTimeoutSeconds': 30
}
```

**Error classes with field lists**
Include a typed list of invalid fields in validation errors for clear debugging:
```python
class ConfigValidationError(Exception):
    def __init__(self, message, invalidFields=None):
        super().__init__(message)
        self.invalidFields = invalidFields or []
```

### Signal Handling

**Double Ctrl+C pattern**
First Ctrl+C sets a shutdown flag, second forces immediate exit:
```python
def _handleSignal(self, signum, frame):
    if self._shutdownRequested:
        sys.exit(1)  # Force exit on second Ctrl+C
    self._shutdownRequested = True
```

**Restore original handlers**
Store and restore original signal handlers on shutdown:
```python
self._originalHandler = signal.signal(signal.SIGINT, self._handleSignal)
# In shutdown:
signal.signal(signal.SIGINT, self._originalHandler)
```

### Blocklist Parsing

**Hosts format uses multiple prefixes**
Both `0.0.0.0` and `127.0.0.1` are valid prefixes in hosts files:
```python
if line.startswith('0.0.0.0 ') or line.startswith('127.0.0.1 '):
    domain = line.split()[1]
```

**EasyList selective parsing**
Only parse `||domain.com^` rules from EasyList; ignore `@@`, `/`, and other rule types:
```python
if line.startswith('||') and line.endswith('^'):
    domain = line[2:-1]  # Strip || and ^
```

**Skip localhost entries in hosts files**
Filter out localhost, local, and localhost.localdomain from hosts file parsing.

### VIN Decoding

**VIN validation rules**
VINs must be exactly 17 characters, alphanumeric only, and exclude I, O, Q (easily confused with 1, 0):
```python
EXCLUDED_CHARS = set('IOQ')
def validateVin(vin: str) -> bool:
    vin = vin.upper().strip().replace('-', '').replace(' ', '')
    return len(vin) == 17 and vin.isalnum() and not any(c in EXCLUDED_CHARS for c in vin)
```

**NHTSA API response handling**
NHTSA returns "Not Applicable", "N/A", or empty strings for unknown fields - parse as NULL:
```python
NA_VALUES = {'Not Applicable', 'N/A', '', None}
value = None if rawValue in NA_VALUES else rawValue
```

**Use urllib for zero dependencies**
For simple API calls, use urllib instead of requests to avoid external dependencies:
```python
from urllib.request import urlopen, Request
req = Request(url, headers={'User-Agent': 'Eclipse OBD-II Monitor/1.0'})
with urlopen(req, timeout=30) as response:
    data = json.loads(response.read().decode())
```

### Database Patterns

**SQLite temp databases for tests**
Use file-based temp databases (not `:memory:`) for tests needing indexes, persistence, or FK constraints:
```python
import tempfile
dbPath = tempfile.mktemp(suffix='.db')  # Not :memory:
```

**INSERT OR REPLACE for caching**
Use INSERT OR REPLACE for database caching patterns:
```sql
INSERT OR REPLACE INTO vehicle_info (vin, make, model, year) VALUES (?, ?, ?, ?)
```

**Foreign key constraint handling**
Profile ID must be NULL (not a missing profile name) when not specified to avoid FK constraint failures:
```python
profileId = config.get('activeProfile') or None  # None for FK safety
```

### Ollama/AI Integration

**Ollama API endpoints**
- `/` - Health check (returns "Ollama is running")
- `/api/version` - Get version info
- `/api/tags` - List installed models
- `/api/pull` - Download model (streaming progress)
- `/api/generate` - Generate text (use `stream: false`)

**Ollama timeouts**
Use different timeouts for different operations:
```python
OLLAMA_HEALTH_TIMEOUT = 5   # Quick health checks
OLLAMA_GENERATE_TIMEOUT = 120  # Model inference (longer)
OLLAMA_PULL_TIMEOUT = 600  # Model downloads (longest)
```

**Analysis rate limiting**
Track analyses per drive ID to prevent excessive API calls:
```python
_analysisCountByDrive: Dict[str, int] = {}
maxAnalysesPerDrive = config.get('maxAnalysesPerDrive', 1)
```

**Graceful degradation when ollama unavailable**
The AI subsystem gracefully handles ollama unavailability without affecting other system functionality:
- If AI analysis is disabled in config, `analyzePostDrive()` returns result with error message and logs at `debug` level
- If ollama is not running or model not loaded, `isReady()` returns False and analysis is skipped with `warning` level log
- `OllamaManager` checks availability on initialization, logs warning if enabled but unavailable, then continues
- Functions return safe defaults (empty lists, False, None) rather than throwing exceptions
- The post-drive workflow completes successfully even when AI is unavailable - statistics are still calculated and stored

### State Machine Patterns

**Drive detection state machine**
STOPPED → STARTING → RUNNING → STOPPING → STOPPED with duration-based transitions:
```python
class DriveState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"  # RPM > 500, timing for duration
    RUNNING = "running"    # Duration met, drive active
    STOPPING = "stopping"  # RPM = 0, timing for duration
```

**Duration-based detection**
Track when condition started, reset if condition drops before duration met:
```python
if rpmAboveThreshold:
    if self._aboveThresholdSince is None:
        self._aboveThresholdSince = time.time()
    elif time.time() - self._aboveThresholdSince >= requiredDuration:
        self._transitionTo(DriveState.RUNNING)
else:
    self._aboveThresholdSince = None  # Reset on drop
```

### Hardware Abstraction

**Pluggable reader pattern**
Use pluggable readers for hardware abstraction (GPIO, I2C, mock):
```python
def setVoltageReader(self, reader: Callable[[], Optional[float]]) -> None:
    self._voltageReader = reader

# Usage for GPIO ADC:
monitor.setVoltageReader(createAdcVoltageReader(channel=0))
# Usage for testing:
monitor.setVoltageReader(lambda: 12.5)
```

**Adafruit import handling**
Adafruit `board` module raises NotImplementedError on non-RPi - catch multiple exception types:
```python
try:
    import board
    from adafruit_rgb_display import st7789
    DISPLAY_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError):
    DISPLAY_AVAILABLE = False
```

**Lazy hardware initialization**
Allow object creation on non-Pi for testing by deferring hardware init:
```python
def __init__(self, config):
    self._config = config
    self._i2cClient = None  # Lazy init

def _ensureInitialized(self):
    if self._i2cClient is None:
        self._i2cClient = I2cClient(self._config['bus'])
```

**HardwareManager integration order**
Initialize hardware after display (so display fallback available), shutdown before display:
```python
def _initializeAllComponents(self):
    self._initializeDisplay()      # First
    self._initializeHardwareManager()  # After display
    self._initializeDataComponents()

def _shutdownAllComponents(self):
    self._shutdownHardwareManager()  # Before display
    self._shutdownDisplay()          # Last
```

### I2C Communication

**I2C error codes - don't retry device-not-found**
OSError errno 121 = Remote I/O, 6 = ENXIO, 19 = ENODEV - these mean device not present, don't retry:
```python
NO_RETRY_ERRNOS = {6, 19, 121}
try:
    return self._bus.read_byte_data(address, register)
except OSError as e:
    if e.errno in NO_RETRY_ERRNOS:
        raise I2cDeviceNotFoundError(f"No device at 0x{address:02X}")
    raise I2cCommunicationError(str(e))  # Retryable
```

**Mocking smbus2 imports in tests**
Use patch.dict to mock hardware library imports:
```python
@patch.dict('sys.modules', {'smbus2': MagicMock()})
def test_i2c_client():
    from src.hardware.i2c_client import I2cClient
    # smbus2 is now mocked
```

**I2C context manager pattern**
Use context manager for automatic bus cleanup:
```python
class I2cClient:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

# Usage
with I2cClient(bus=1) as client:
    voltage = client.readWord(0x36, 0x02)
```

**UPS signed 16-bit current**
UPS current register uses signed 16-bit: if raw > 32767, subtract 65536:
```python
rawCurrent = self._client.readWord(address, CURRENT_REGISTER)
if rawCurrent > 32767:
    rawCurrent -= 65536  # Convert to signed
return rawCurrent  # Positive = charging, negative = discharging
```

### GPIO and gpiozero

**gpiozero Button configuration**
bounce_time for debounce, hold_time for long press:
```python
from gpiozero import Button
button = Button(
    pin=17,
    pull_up=True,        # Active low (button connects to GND)
    bounce_time=0.2,     # 200ms hardware debounce
    hold_time=3.0        # 3 seconds for long press
)
button.when_held = onLongPress
button.when_released = onShortPress
```

**gpiozero exception handling**
gpiozero raises multiple exception types on non-Pi:
```python
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError, NotImplementedError):
    GPIO_AVAILABLE = False
```

### Pygame Display

**pygame exception handling on non-Pi**
pygame may raise RuntimeError on non-Pi systems:
```python
try:
    import pygame
    PYGAME_AVAILABLE = True
except (ImportError, RuntimeError):
    PYGAME_AVAILABLE = False
```

**pygame kiosk/embedded display**
Use NOFRAME and hide cursor for touch displays:
```python
pygame.init()
screen = pygame.display.set_mode((480, 320), pygame.NOFRAME)
pygame.mouse.set_visible(False)  # Hide cursor for touch
```

**Get local IP without network connection**
Use socket UDP connect trick:
```python
def getLocalIp() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))  # Doesn't actually send anything
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'
```

### Logging Patterns

**Unique logger per instance**
Create unique logger to avoid conflicts:
```python
self._logger = logging.getLogger(f"telemetry.{id(self)}")
self._logger.propagate = False  # Avoid duplicate output to root
```

**RotatingFileHandler encoding**
Always specify encoding:
```python
handler = RotatingFileHandler(
    logPath,
    maxBytes=100*1024*1024,  # 100MB
    backupCount=7,
    encoding='utf-8'
)
```

### System Telemetry

**CPU temperature on Raspberry Pi**
Value in /sys is millidegrees Celsius:
```python
def getCpuTemp() -> Optional[float]:
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return int(f.read().strip()) / 1000.0  # Convert to Celsius
    except (FileNotFoundError, ValueError):
        return None
```

**Cross-platform disk space**
shutil.disk_usage works everywhere:
```python
import shutil
usage = shutil.disk_usage('/')
freeGb = usage.free / (1024**3)
```

**JSON serialization with datetime/enum**
Use default=str for automatic conversion:
```python
import json
data = {'timestamp': datetime.now(), 'status': SomeEnum.VALUE}
jsonStr = json.dumps(data, default=str)
```

### Destructor Safety

**Check hasattr in __del__**
__del__ may be called on partially initialized objects:
```python
def __del__(self):
    if hasattr(self, '_lock') and hasattr(self, '_timer'):
        with self._lock:
            if self._timer:
                self._timer.cancel()
```

### Display Patterns

**Double-buffering with PIL**
Use PIL Image for smooth display updates:
```python
image = Image.new('RGB', (240, 240), color=(0, 0, 0))
draw = ImageDraw.Draw(image)
draw.text((10, 10), "RPM: 3500", fill=(255, 255, 255))
display.image(image)  # Blit to hardware
```

**Color temperature ranges**
Standard temperature color coding for coolant:
```python
if temp < 60: color = BLUE      # Cold
elif temp < 100: color = WHITE  # Normal
elif temp < 110: color = ORANGE # Warm
else: color = RED               # Hot/Critical
```

### Export Patterns

**CSV file handling on Windows**
Always use `newline=''` when opening CSV files:
```python
with open(filepath, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
```

**Export filename convention**
Use date range format for export filenames:
```python
filename = f"obd_export_{startDate:%Y-%m-%d}_to_{endDate:%Y-%m-%d}.csv"
```

### Profile and Calibration

**Pending switch pattern**
Queue profile changes when driving, activate on next drive start:
```python
def requestProfileSwitch(self, profileId: str) -> bool:
    if self._isDriving:
        self._pendingSwitch = profileId
        return False  # Queued, not immediate
    return self._activateProfile(profileId)
```

**Force parameter for dangerous operations**
Use `force=True` pattern for operations that need explicit override:
```python
def deleteSession(self, sessionId: str, force: bool = False) -> bool:
    if self._currentSession and self._currentSession.id == sessionId:
        if not force:
            raise CalibrationSessionError("Cannot delete active session")
        self._currentSession = None  # Clear internal state too
```

### Text Similarity

**Jaccard similarity for deduplication**
Simple but effective for text similarity:
```python
def jaccardSimilarity(text1: str, text2: str) -> float:
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union) if union else 0.0
```

**Variance calculation for drift detection**
Use min-max variance (not mean deviation) for comparing sessions:
```python
variance = ((maxValue - minValue) / minValue) * 100 if minValue > 0 else 0
isSignificant = variance > SIGNIFICANCE_THRESHOLD  # 10%
```

### Simulator Patterns

**CLI --simulate flag pattern**
Enable simulator mode via CLI flag or config:
```python
# CLI flag overrides config when present
isSimulating = args.simulate or isSimulatorEnabled(config)
```

**Platform-specific keyboard input**
Use msvcrt on Windows, select on Unix for non-blocking input:
```python
if sys.platform == 'win32':
    import msvcrt
    if msvcrt.kbhit():
        char = msvcrt.getch().decode('utf-8', errors='ignore')
else:
    import select
    if select.select([sys.stdin], [], [], 0)[0]:
        char = sys.stdin.read(1)
```

**Smooth scenario transitions**
Rate-limit throttle changes for realistic behavior:
```python
maxChange = TRANSITION_RATE_PER_SEC * deltaSeconds
actualChange = min(abs(target - current), maxChange)
newValue = current + (actualChange if target > current else -actualChange)
```

**Auto gear selection by speed**
Simple threshold-based gear selection:
```python
if speedKph < 15: gear = 1
elif speedKph < 30: gear = 2
elif speedKph < 50: gear = 3
elif speedKph < 80: gear = 4
else: gear = 5
```

### Test Debugging

**Database wrapper exceptions**
Database `connect()` context manager wraps sqlite3.Error as DatabaseConnectionError - expect the wrapper:
```python
# Tests should expect wrapper exception, not raw sqlite3 errors
with pytest.raises(DatabaseConnectionError) as exc:
    db.insertRecord(invalidData)
assert "constraint" in str(exc.value).lower()
```

**Empty list edge case**
Handle empty list before indexing:
```python
# BAD - IndexError if list is empty
delay = delays[min(attempt, len(delays) - 1)]

# GOOD - Handle empty case
delay = delays[min(attempt, len(delays) - 1)] if delays else 0
```

### Module Refactoring Patterns

**Standard module structure**
When refactoring monolithic modules into subpackages, follow this order:
1. `types.py` - Enums, dataclasses, constants (zero project dependencies, stdlib only)
2. `exceptions.py` - Custom exceptions (may import from types)
3. Pure function modules (e.g., `calculations.py`, `thresholds.py`)
4. Core class modules (e.g., `manager.py`, `engine.py`)
5. `helpers.py` - Factory functions, config helpers

**Backward compatibility via re-exports**
Keep original module as a facade that re-exports from the new subpackage:
```python
# src/obd/data_logger.py (original location)
from obd.data import (
    DataLoggerError,
    ObdDataLogger,
    RealtimeDataLogger,
    # ... all public symbols
)
__all__ = [...]  # Re-export everything
```

**Test patches must target actual implementation**
When code moves to a subpackage, patches must target the new location:
```python
# BAD - Patches the re-export, not the actual code
@patch('obd.ai_analyzer.urllib')

# GOOD - Patches where the code actually lives
@patch('obd.ai.analyzer.urllib')
```

**Avoiding circular imports**
Use `TYPE_CHECKING` for type hints that would cause circular imports:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from obd.analysis.engine import StatisticsEngine

def createAnalyzer(engine: 'StatisticsEngine') -> AiAnalyzer:
    pass
```

**Package/module name collision**
When a package directory shadows a module file (e.g., `service/` shadows `service.py`), use importlib.util:
```python
# In src/obd/service/__init__.py
import importlib.util
import os
_sibling = os.path.join(os.path.dirname(__file__), '..', 'service.py')
_spec = importlib.util.spec_from_file_location('_service_module', _sibling)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
# Now re-export from _module
```

---

## Git Branching Strategy

Follow sprint-based branching:

1. **Sprint branches**: Create a branch per sprint (e.g., `sprint/2026-02-sprint1`)
2. **Work on the sprint branch**: All feature work during the sprint goes on the sprint branch
3. **Merge to main**: When the sprint is done and tests pass, merge the sprint branch back to `master`
4. **Never push directly to master** during active sprint work

```bash
# Start a sprint
git checkout -b sprint/2026-02-sprint1 master

# Work on the sprint branch
git add <files>
git commit -m "feat: description"

# End of sprint - merge to master
git checkout master
git merge sprint/2026-02-sprint1
git push origin master
```

---

## PM Communication Protocol

Ralph communicates with the Project Manager via files in the `pm/` directory:

| Folder | Purpose | When to Use |
|--------|---------|-------------|
| `pm/blockers/` | Items blocking progress | When stuck and cannot proceed |
| `pm/techDebt/` | Known technical debt | When spotting code quality concerns |
| `pm/issues/` | Bugs or problems found | When finding bugs or inconsistencies |

**Important**:
- `specs/` is read-only for Ralph. Request changes via `pm/issues/`.
- `pm/backlog/` is PM-only. Ralph does not write there.
- **Always report back**: If you encounter a blocker, find a bug, or identify tech debt during implementation, create the appropriate file in `pm/blockers/`, `pm/issues/`, or `pm/techDebt/` immediately. Do not silently work around problems -- the PM needs visibility into anything that could affect the project.

---

## Housekeeping Patterns

Periodic housekeeping sessions should check:

1. **Stale files**: Dead code referencing deleted files, garbage artifacts (Windows 8.3 filenames), orphaned test runners
2. **Config drift**: Multiple config files diverging, example configs becoming inconsistent with actual project config
3. **Specs drift**: Documentation falling behind code changes (display dimensions, deleted features still referenced, missing new features)
4. **Requirements drift**: Duplicate packages across requirements files, dev tools in production requirements
5. **Agent state**: Stale task IDs and dates in ralph_agents.json; archive completed PRDs
6. **Test health**: Run full suite, check for warnings (e.g., TestDataManager __init__ collection issue)
7. **File sizes**: Flag files exceeding guidelines (~300 source, ~500 test) for splitting

**Key lesson**: Specs drift from code faster than expected. After any major feature push or hardware change, audit specs for stale references.

**Key lesson**: Keep exactly one config file, one requirements file. Duplicates always diverge.

**Key lesson**: When changing defaults in code (like CLI --config path), search tests for assertions on the old value.

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-29 | Ralph | Added git branching strategy, PM communication protocol, housekeeping patterns, and lessons learned |
| 2026-01-26 | Knowledge Update | Added Raspberry Pi hardware patterns: I2C communication, GPIO/gpiozero, pygame display, logging, system telemetry, destructor safety, HardwareManager integration order |
| 2026-01-26 | Knowledge Update | Added threading patterns: clean interruption with Event.wait(), exception-safe polling callbacks |
| 2026-01-22 | Knowledge Update | Added module refactoring patterns (structure, backward compat, test patches, circular imports, name collisions) |
| 2026-01-22 | Knowledge Update | Added simulator patterns (CLI flag, keyboard input, transitions, auto gear), test debugging tips |
| 2026-01-22 | Knowledge Update | Added VIN decoding, database, Ollama, state machine, hardware, display, export, profile, calibration, and text similarity patterns |
| 2026-01-21 | M. Cornelison | Added operational tips section with learnings from adMonitor implementation |
