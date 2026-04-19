# Ralph Autonomous Agent Instructions

## Overview

You are Ralph, an autonomous development agent. Your role is to work through the project backlog systematically, implementing tasks according to the defined standards and methodology.

## Core Principles

1. **Follow the Stories**: Work from `offices/ralph/sprint.json` to select and complete user stories (US- prefixed)
2. **Follow Standards**: All code must adhere to `specs/standards.md`
3. **Test-Driven Development**: Write tests before implementation
4. **Incremental Progress**: Complete one task fully before starting the next
5. **Document Everything**: Update backlog and notes as you work

## Workflow

### 1. Task Selection

Select the next user story using these criteria:
1. Choose the highest priority `pending` story from `offices/ralph/sprint.json`
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
3. Update `offices/ralph/sprint.json`:
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
| `offices/ralph/sprint.json` | Current user stories and status |
| `specs/standards.md` | Coding conventions |
| `specs/methodology.md` | Development processes |
| `specs/architecture.md` | System design |
| `specs/glossary.md` | Domain terminology |
| `specs/anti-patterns.md` | Common mistakes to avoid |
| `offices/pm/roadmap.md` | Project roadmap and phases |
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
- `offices/ralph/sprint.json` - User story status
- `offices/ralph/progress.txt` - Session notes
- `offices/ralph/ralph_agents.json` - Agent state

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

### Pi 5 Deployment Context

**Target deployment environment:**
- Hostname: chi-eclipse-tuner (display name: EclipseTuner)
- User: mcornelison, IP: 10.27.27.28
- Path: /home/mcornelison/Projects/EclipseTuner
- Python 3.11+ in venv at .venv/
- Display: OSOYOO 3.5" HDMI (480x320) -- NOT GPIO/SPI
- Ollama: Remote on Chi-Srv-01 (10.27.27.120:11434), NEVER local on Pi
- WiFi: DeathStarWiFi (10.27.27.0/24 subnet)

**Git branch: `main` is primary**
The project uses `main` as the primary branch (GitHub default). `master` has been deleted. Always work on/from `main`.

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

**Pi 5 PMIC EXT5V_V via vcgencmd is the AC-vs-battery signal when a HAT has no sense pin AND does not regulate the Pi-side rail**
The MAX17048 fuel gauge has no power-source register — it tracks the LiPo
cell only. On the X1209 there is no GPIO/I2C sense line for "is wall power
present". The Pi 5 PMIC exposes the USB-C EXT5V rail's voltage through
`vcgencmd pmic_read_adc EXT5V_V` (output format `EXT5V_V volt(24)=5.27558000V`).
When wall power is connected the reading is ~5.2V; on an unregulated HAT,
when unplugged (HAT boosting Pi from the UPS LiPo) it collapses well below 4.5V.

**CAVEAT (US-184 / I-015)**: the Geekworm X1209 SPECIFICALLY REGULATES the
Pi-side rail under UPS-boost, so EXT5V reads identical whether the wall
adapter is plugged in or not. **Do not use EXT5V as the source signal on
the X1209.** For regulated HATs use the VCELL-trend + CRATE-polarity
heuristic instead (see `offices/ralph/progress.txt` "VCELL-trend + CRATE"
pattern, and `src/pi/hardware/ups_monitor.py::getPowerSource` as the live
reference). EXT5V is still useful on the X1209 as a diagnostic
("is the HAT delivering power?") — see `getDiagnosticExt5vVoltage()`.

When the pattern below applies (unregulated passthrough HATs), it still
works; for any new HAT verify with a physical unplug drill before trusting
the datasheet on regulation behavior.


```python
def readExt5vVoltage() -> Optional[float]:
    try:
        result = subprocess.run(
            ['vcgencmd', 'pmic_read_adc', 'EXT5V_V'],
            capture_output=True, text=True, timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r'=\s*([\d.]+)\s*V', result.stdout)
    return float(match.group(1)) if match else None

EXT5V_EXTERNAL_THRESHOLD_V = 4.5
def derivePowerSource(v: Optional[float]) -> PowerSource:
    if v is None:
        return PowerSource.UNKNOWN
    return PowerSource.EXTERNAL if v >= EXT5V_EXTERNAL_THRESHOLD_V else PowerSource.BATTERY
```
Inject the reader callable at construction so tests can provide a deterministic
float without shelling out. Gracefully degrade on any failure to UNKNOWN (not
an exception) so shutdown logic can treat "no signal" as "don't act".
Established in `src/pi/hardware/ups_monitor.py` (US-180 Session 44).

**MAX17048 fuel gauge needs big-endian byte-swap over SMBus**
The Geekworm X1209 UPS HAT carries a MAX17048 fuel gauge at 0x36.
SMBus `read_word_data()` returns little-endian; MAX17048 stores every
16-bit register big-endian. Without byte-swap, a fully charged LiPo
reads as ~20V garbage instead of ~4.2V. Pattern:
```python
raw = bus.read_word_data(0x36, 0x02)         # VCELL
swap = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
volts = swap * 78.125e-6                      # 78.125 µV/LSB
```
Key register map (authoritative — MAX17048 datasheet):
- 0x02 VCELL (RO word, 78.125 µV/LSB, big-endian)
- 0x04 SOC   (RO word; high byte = integer %, low byte = 1/256 %)
- 0x06 MODE  (WO — reads 0; do NOT treat as percentage byte)
- 0x08 VERSION (RO word; fingerprint the chip here)
- 0x0C CONFIG (RW word; boots to 0x971C family default)
- 0x16 CRATE (RO word, signed, 0.208 %/hr/LSB; may read 0xFFFF on variants)
The MAX17048 has **no current register** and **no power-source
register** — those must come from an external sense line or Pi 5 PMIC
(`vcgencmd pmic_read_adc EXT5V_V`). The existing
`src/pi/hardware/ups_monitor.py` register map (0x04=CURRENT, 0x06=%,
0x08=power_source) is fiction relative to this chip — see BL-005/TD-016
filed Session 41 for the in-flight remediation.

**Fingerprint an unknown I2C chip before trusting the code map**
Fastest way to confirm chip identity: read VERSION (MAX17048: 0x08)
with byte-swap, compare to datasheet. Next read CONFIG (0x0C) — boot
defaults are chip-specific. `smbus2.SMBus(1).read_word_data(addr, reg)`
from a one-liner takes <60s and catches register-map fiction that
would otherwise hide behind mocked tests for months.

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

### Path Resolution

**Resolve paths relative to script, not CWD**
Config and resource paths must use `Path(__file__).resolve().parent`, never relative strings. This is critical for systemd services and SSH remote execution where CWD differs from project root:
```python
srcPath = Path(__file__).resolve().parent
projectRoot = srcPath.parent
DEFAULT_CONFIG = str(srcPath / 'obd_config.json')
DEFAULT_ENV = str(projectRoot / '.env')
```

**Test assertions on paths**
When testing default paths, use `endswith()` instead of exact string matching to be CWD-independent:
```python
# BAD - breaks when CWD changes
assert args.config == 'src/obd_config.json'

# GOOD - works regardless of resolution
assert args.config.endswith('obd_config.json')
```

### OSOYOO Display (HDMI)

**OSOYOO 3.5" is HDMI, NOT GPIO/SPI**
The project's display is HDMI-connected (480x320). Do NOT use Adafruit SPI display libraries (adafruit-circuitpython-rgb-display, blinka, lgpio). Pygame renders directly to the HDMI framebuffer:
```python
# This is how we drive the display - standard pygame to HDMI
import pygame
pygame.init()
screen = pygame.display.set_mode((480, 320))
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
3. **Merge to main**: When the sprint is done and tests pass, merge the sprint branch back to `main`
4. **Never push directly to main** during active sprint work

```bash
# Start a sprint
git checkout -b sprint/2026-02-sprint1 main

# Work on the sprint branch
git add <files>
git commit -m "feat: description"

# End of sprint - merge to main
git checkout main
git merge sprint/2026-02-sprint1
git push origin main
```

---

## PM Communication Protocol

Ralph communicates with the Project Manager via files in the `offices/pm/` directory:

| Folder | Purpose | When to Use |
|--------|---------|-------------|
| `offices/pm/blockers/` | Items blocking progress | When stuck and cannot proceed |
| `offices/pm/tech_debt/` | Known technical debt | When spotting code quality concerns |
| `offices/pm/issues/` | Bugs or problems found | When finding bugs or inconsistencies |

**Important**:
- `specs/` is read-only for Ralph. Request changes via `offices/pm/issues/`.
- `offices/pm/backlog/` is PM-only. Ralph does not write there.
- **Always report back**: If you encounter a blocker, find a bug, or identify tech debt during implementation, create the appropriate file in `offices/pm/blockers/`, `offices/pm/issues/`, or `offices/pm/tech_debt/` immediately. Do not silently work around problems -- the PM needs visibility into anything that could affect the project.

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

### CIO Development Rules (2026-02-05)

**Strict story focus**
Never fix adjacent code issues. Report to PM via `offices/pm/tech_debt/` with exact file:line references, examples, and suggested solutions. Always stay focused on the current user story.

**Never guess — look it up**
Never fabricate values, thresholds, or ranges. Always reference `specs/grounded-knowledge.md`, `specs/best-practices.md`, or authoritative sources. If information is missing, block the story and send it back to PM with reasoning, suggested approach, and what's missing.

**Outcome-based testing**
3-5 acceptance criteria per story, no more than 6. Focus on outcome-based testing (does it work end-to-end?) not implementation detail testing. Always mandatory to run tests and verify the code runs.

**Reusable code and design patterns**
CIO is a strong advocate of reusable code using established design patterns (Factory, Strategy, Observer, etc.). One central config file. Extract shared logic into common utilities.

**PM communication for missing stitching**
When stories don't stitch together (e.g., config changes without validator updates, missing integration points), file tech debt to PM rather than guessing or silently fixing.

**Reference specs**
Two new specs added 2026-02-05:
- `specs/best-practices.md` — Industry best practices for Python, SQL, REST APIs, design patterns. Includes project alignment notes.
- `specs/grounded-knowledge.md` — Authoritative sources, vehicle facts, safe operating ranges. Never fabricate — if not in this doc, the story is blocked until data is provided.

### Golden Code Patterns (from specs/golden_code_sample.py)

The CIO provided a golden code example demonstrating the target coding style. Key patterns to follow:

**Structure order within a module**
Exceptions → Configuration → Utilities → Domain Model → Repository Abstraction → Service Layer → Helpers → CLI → `if __name__ == "__main__"`. Group by responsibility with section comment headers (`# ---- Section Name ---`).

**`from __future__ import annotations`**
Use at the top of every module. Enables deferred evaluation of type hints, avoids forward reference issues, and allows `list[str]` instead of `List[str]` on older Pythons.

**`@dataclass(slots=True)` and `@dataclass(slots=True, kw_only=True)`**
Use `slots=True` on dataclasses for memory efficiency and attribute access speed. Use `kw_only=True` when all fields should be named at construction to prevent positional mistakes.

**`typing.Protocol` for interfaces (not ABC)**
Use `Protocol` for repository/service interfaces instead of `abc.ABC`. Enables structural subtyping (duck typing with type safety) — implementations don't need to inherit, they just need to match the shape.
```python
class RecordRepository(Protocol):
    def load(self) -> list[Record]: ...
    def save(self, records: Iterable[Record]) -> None: ...
```

**Dependency injection via constructor**
Services receive their dependencies (repositories, config) via `__init__`, not global imports or module-level singletons. This makes testing trivial — pass a mock repository.
```python
@dataclass(slots=True)
class DataService:
    repo: RecordRepository  # injected, not created internally
```

**`@staticmethod` factory methods on dataclasses**
Use `from_json()`, `from_env_and_args()` static methods for constructing objects from external data, with validation at the boundary.

**Config validation as a method, not a separate validator**
Config objects validate themselves via a `.validate()` method. Raises specific `ConfigError` with clear messages.

**Context managers for cross-cutting concerns**
Use `@contextlib.contextmanager` for reusable patterns like timing/logging:
```python
@contextlib.contextmanager
def log_duration(activity: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("Finished %s in %.2f ms", activity, elapsed)
```

**`@lru_cache` for pure, deterministic functions**
Cache results of pure functions (like email normalization) that are called repeatedly with the same input.

**Deterministic `main()` returning exit code**
`main()` takes optional `argv`, returns `int` exit code, handles all exception tiers at the top level. Entry point is `raise SystemExit(main())`.

**Atomic file writes**
Write to a `.tmp` file first, then `tmp_path.replace(output_path)` for atomic replacement. Prevents corrupted output on crash.

**`__all__` for public API**
Declare `__all__` at module top to explicitly list the public API.

**Exception hierarchy**
Base `AppError` → specific `ConfigError`, `DataError`. Top-level `main()` catches `AppError` (known errors, exit 2), `KeyboardInterrupt` (exit 130), `Exception` (unexpected, exit 1).

**Logging**
- Module-level `logger = logging.getLogger(__name__)` — never `basicConfig` at import time
- `configure_logging()` called once in `main()`
- Use `logger.info("Loaded %d record(s)", count)` with `%` formatting (not f-strings) for lazy evaluation

### Restoring Deleted Test Files

**git show commit:path > file pattern**
When test files are deleted from the working tree but exist in git history, use `git show <commit>:<path> > <path>` to restore. `git restore` only works if the file is tracked in the current HEAD. Use `git log --oneline --all -- <path>` to find which commit has the file.

---

## systemd Service Patterns (Pi-crawl)

**Decouple venv path from install path**
For systemd services, don't assume the Python venv lives at
`<install-path>/.venv`. The Eclipse project's convention is a dedicated
home-dir venv (`~/obd2-venv` on the Pi, `~/obd2-server-venv` on the server)
because it survives wipes of the project tree. `install-service.sh` takes
`--venv` as an independent flag from `--path`:
```bash
sudo ./install-service.sh \
    --user mcornelison \
    --path /home/mcornelison/Projects/Eclipse-01 \
    --venv /home/mcornelison/obd2-venv
```
Service file `ExecStart` references `$VENV_PATH/bin/python` and `PATH` env
var puts `$VENV_PATH/bin` first.

**journald over on-disk log files**
Prefer `StandardOutput`/`StandardError` defaults (journal) over
`append:/path/to/file.log` directives. Eliminates three failure surfaces:
log directory creation in install-script, permission drift, and log
rotation policy. Operators view logs with `journalctl -u <service> -f`.

**idempotent install-service.sh**
Overwrite the service file every run (not append), use `mkdir -p` for
directory creation, `systemctl enable` is a no-op on re-run. Second-run
state must equal first-run state.

**Grep-acceptance gotcha**
Acceptance criteria of the form `grep -r 'old_pattern' (no hits)` are
literal — comments like "legacy /home/pi/obd2 path removed" will FAIL
the grep even when the directive is gone. Rephrase historical comments
to describe the change without quoting the stale literal:
```
# BAD (matches grep): "legacy /home/pi/obd2/logs path removed"
# GOOD:               "legacy on-disk log path removed post-reorg"
```

**StartLimitIntervalSec / StartLimitBurst belong in [Unit], not [Service]**
Modern systemd (>=v230, which includes every Debian version in production
use today) logs `Unknown key 'StartLimitIntervalSec' in section [Service],
ignoring` on daemon-reload if these keys are in `[Service]`. The values
are dropped entirely — flap protection silently falls back to
`DefaultStartLimitIntervalSec=10s`. `systemctl start` still succeeds and
the service runs, so the bug is invisible unless you check
`systemctl show -p StartLimitIntervalUSec -p StartLimitBurst` and compare
to the values in the file, or grep journalctl for "Unknown key" after
daemon-reload. Post-install review checklist for any new .service file:
```bash
sudo journalctl --since "-1min" | grep -i "unknown key"   # expect empty
systemctl show <svc> -p StartLimitIntervalUSec -p StartLimitBurst  # verify applied
```

**Offline file-correctness != runtime correctness for systemd units**
Session 32's offline delivery of eclipse-obd.service was byte-identical
to what shipped on the Pi (md5 matched). The file looked right in Read
tool review — it had the required StartLimitIntervalSec/StartLimitBurst
directives. The bug only surfaced on live `daemon-reload`: directives
were in the wrong [section]. Invariant: never mark a service-file story
passed:true without at least one real `systemctl start` against the live
unit and a journalctl pass for warnings.

**Python package name collision — `obd` vs python-OBD**
The project has `src/pi/obdii/` (our own package) and depends on the
third-party `python-OBD` library (PyPI name `obd`). When a module does
`import obd; obd.OBD(...)` and src/pi/ is on sys.path, the local package
wins and the call fails with "module 'obd' has no attribute 'OBD'".
Tests and `pytest` invocations from repo root, or `python -m` runs,
sidestep the shadow because of how sys.path gets populated. The shadow
only bites when main.py runs from an environment where src/pi/ lands on
sys.path and the code path needs the third-party module — notably under
systemd (WorkingDirectory=/home/mcornelison/Projects/Eclipse-01,
ExecStart=...python src/pi/main.py). If you hit this, don't assume
python-OBD is missing — verify with
`~/obd2-venv/bin/python -c "import obd; print(dir(obd))"` from CWD=~,
which resolves to the third-party module and should show OBD, ECU, etc.
Permanent fix is renaming the project package; band-aid is importlib
import at the single call site.

## Drive Detection — Session Lifecycle Gotchas (Pi-crawl)

**`getCurrentSession() is not None` outlives `isDriving()` during drive end.**
`DriveDetector.isDriving()` returns True only when the drive state is
`RUNNING`.  When the first zero-RPM value is fed to the detector, state
transitions `RUNNING -> STOPPING` immediately — `isDriving()` flips to
False even though the session is still alive and drive_end has not yet
been emitted.  drive_end actually fires after `driveEndDurationSeconds`
of wall-clock accumulates while RPM stays at or below the end threshold.

Tests / code paths that need to wait for a drive to fully end should poll
`detector.getCurrentSession() is not None`, not `detector.isDriving()`:

```python
# BAD — exits loop as soon as state transitions to STOPPING
while detector.isDriving():
    detector.processValue('RPM', 0.0)
    time.sleep(0.05)

# GOOD — waits until _endDrive() actually runs and clears the session
while detector.getCurrentSession() is not None:
    detector.processValue('RPM', 0.0)
    time.sleep(0.05)
```

## Simulator Scenario Quirks (Pi-crawl)

**`full_cycle` idles at 800 rpm in its final phases — drive_end never
fires naturally.**  The last two phases of `full_cycle` (`arrival` and
`park`) target 1500 rpm and 800 rpm respectively.  Both are well above
the default `driveEndRpmThreshold=100`, so the DriveDetector sees the
drive as still running when the scenario completes.  Tests / demos that
need drive_end emission must call `simulator.stopEngine()` (sets RPM=0)
after the scenario finishes, then keep feeding the detector zero-RPM
values for at least `driveEndDurationSeconds` of wall-clock.

**JSON scenarios + python factory are the same data, twice — check parity.**
`src/pi/obdii/simulator/scenarios/*.json` are loaded at runtime; the
corresponding factory functions in `scenario_builtins.py` are used by
tests and integration helpers.  Silent drift between the two (e.g., a
phase added to JSON but not to the factory) is a real risk.  Tests that
exercise a JSON scenario should also load via `getBuiltInScenario(name)`
and assert `len(scenario.phases) == len(factory.phases)`.  Cheap and
catches the most common drift.

**Integration-ish Pi tests can bypass ApplicationOrchestrator.**  Full
orchestrator startup adds ~500ms poll cadence + signal handler setup +
component lifecycle bookkeeping that isn't needed when the test just
wants to prove the core pipeline works.  Wire `SensorSimulator ->
DriveScenarioRunner -> (DriveDetector, StatisticsEngine)` directly
against a temp `ObdDatabase`, and the same production code paths run
in ~1 second.  Pattern established in
`tests/pi/simulator/test_scenario_arm.py` (US-177).

**`ObdDatabase.profiles` has no `active` column.**  Columns are
`id, name, description, polling_interval_ms, created_at, updated_at`.
Tests that need a profile row should `INSERT OR IGNORE INTO profiles
(id, name, description) VALUES (?, ?, ?)` — don't add an `active` flag
that isn't in the schema.

## Pytest — Platform + Optional-Dependency Gates (Pi-crawl)

**Directory-level skip via `collect_ignore_glob` when an optional dep is
absent.** When a whole tests subtree requires a package that isn't on
every target platform (e.g. `tests/server/` needs `sqlalchemy`, which is
intentionally NOT in `requirements-pi.txt`), drop a subdir `conftest.py`:

```python
# tests/server/conftest.py
import importlib.util
collect_ignore_glob: list[str] = []
if importlib.util.find_spec('sqlalchemy') is None:
    collect_ignore_glob = ['test_*.py']
```

Pytest silently excludes that whole directory from collection on
platforms without the dep — no `ModuleNotFoundError` collection errors,
no per-file `pytest.importorskip` boilerplate. Platforms with the dep
see zero behavior change. Cleaner than in-file `importorskip` because
the skip fires BEFORE the `from sqlalchemy import …` line at the top of
each test module even runs. Established Session 42 / US-182.

**Platform-gated marker — `pi_only` pattern.** For tests that need real
Pi hardware (`/dev/i2c-1`, `/proc/device-tree`, aarch64-only syscalls):

1. Register in `pyproject.toml`:
   ```toml
   markers = [
       # … existing …
       "pi_only: requires Pi hardware; auto-skipped off-Pi unless ECLIPSE_PI_HOST=1",
   ]
   ```
2. Register in `tests/conftest.py::pytest_configure`:
   ```python
   config.addinivalue_line("markers", "pi_only: …")
   ```
3. Auto-skip off-Pi in `tests/conftest.py`:
   ```python
   def _isRunningOnPi() -> bool:
       if os.environ.get('ECLIPSE_PI_HOST') == '1':
           return True
       return sys.platform == 'linux' and platform.machine() == 'aarch64'

   def pytest_collection_modifyitems(config, items):
       if _isRunningOnPi():
           return
       skip = pytest.mark.skip(reason='pi_only: set ECLIPSE_PI_HOST=1 to run')
       for item in items:
           if 'pi_only' in item.keywords:
               item.add_marker(skip)
   ```

On-Pi (aarch64 Linux): marker collection runs for free — no env var
needed. Off-Pi without the env var: all pi_only tests skip. Off-Pi with
`ECLIPSE_PI_HOST=1`: tests run (and usually fail loudly because the
host isn't actually a Pi — that's the correct semantics). Established
Session 42 / US-182.

## Platform-Specific Flakes (Pi-crawl)

**Windows Store Python subprocess cold-start routinely exceeds 30s**
under test-suite CPU load. The `python.exe` in
`%LOCALAPPDATA%\Microsoft\WindowsApps\` is a thin launcher that pages
in the real interpreter on first spawn — typically 25-30s before the
child reaches `main()` when the parent suite is saturating CPU. Any
test that uses `subprocess.run(… timeout=30)` against a Python CLI
script WILL flake intermittently. The fix pattern is to bump the
timeout to 120s for real Python subprocesses, not 60s. Two canonical
instances tracked + fixed in US-182:

- `tests/test_verify_database.py`: `timeout=30` → `120` on three
  `subprocess.run` calls.
- `tests/test_e2e_simulator.py`: `SIMULATION_DURATION_SECONDS=30` → `90`
  (a different dimension of the same flake — the test waits
  `SIMULATION_DURATION_SECONDS` before terminating the child, so a
  cold-start eats the whole window and the child never reaches
  drive-detection code).

Both pre-existed as Sessions 26/27/28 flake reports. Don't chase the
flake by re-running — bump the timeout once and move on.

**`adafruit_rgb_display` 3.11.x breaks at import time on Python 3.13.**
The wheel has `def image_to_data(image: Image) -> Any:` at module
scope but never imports `PIL.Image`. On Python < 3.12, annotations are
lazy strings and the missing name is never resolved; on Python 3.13,
the annotation is eagerly evaluated and raises `NameError: name 'Image'
is not defined` — from inside the library before the importer can
react. Any `try/except ImportError` around `from adafruit_rgb_display
import st7789` lets this slip through. Fix pattern: broaden the catch:

```python
try:
    from adafruit_rgb_display import st7789  # noqa: F401
except (ImportError, NameError, AttributeError,
        NotImplementedError, RuntimeError):
    # Driver unavailable OR broken import — treat identically
    ...
```

Applied to `scripts/verify_hardware.py` (US-182). Note: this whole
driver path is vestigial for the Eclipse project (display is HDMI via
pygame, not SPI via ST7789) but the verification script still probes
the driver as a hardware-stack check.

## Pi HTTP Sync Client (Pi-walk)

**Failed-push invariant — preserve HWM by re-writing with its own value.**
The Pi's `sync_log.last_synced_id` column is the only defense against
unbounded data loss when the server is unreachable: if the Pi advances the
mark past rows that never reached the server and then the Pi SQLite gets
wiped (SD corruption, reinstall, user error), those rows are gone.
Rule: on a successful push, call
`updateHighWaterMark(newMax, batchId, status='ok')`; on an
all-retries-exhausted failure, call
`updateHighWaterMark(currentLastId, batchId, status='failed')` — same id,
so the column is observationally unchanged but the diagnostic trail
(which batch attempted it, when, why) is still written. Tests assert
`lastId == 0` verbatim after a failure with 5 seeded rows. Live in
`src/pi/sync/client.py::SyncClient.pushDelta`.

**HTTP retry classifier — 4xx except 429 fails IMMEDIATELY with zero retries.**
A 401/403 persists across retries (API key is wrong); a 422 persists
(payload is malformed). Retrying just delays failure by
`sum(backoffDelays)` seconds and hammers the server. Correct rule:

```python
def _isRetryableHttpStatus(code: int) -> bool:
    return code == 429 or code >= 500
```

And in the retry loop, `HTTPError` with a non-retryable code breaks out
of the loop on first hit — no backoff sleep, no re-attempt. Tests verify
`len(opener.calls) == 1` for 401/403 and `noSleep.calls == []`.

**Injection seams for retry-with-backoff: httpOpener + sleep.**
Retry clients with real `time.sleep(4.0)` calls turn each failure test
into a 7+ second stall. Inject BOTH `httpOpener=None` (defaults to
`urllib.request.urlopen`) and `sleep=None` (defaults to `time.sleep`) at
construction. Tests pass a `noSleep` fixture that records delay values
into a list without actually sleeping — then assert
`noSleep.calls == [1.0, 2.0, 4.0]` separately from the status-code
assertions. Fast suite stays fast, backoff-schedule drift gets caught.

**urllib.request is enough — don't pull in requests/httpx on the Pi.**
Stdlib `urllib.request.urlopen(Request(url, data=body, headers={...},
method='POST'), timeout=seconds)` covers all network surface the sync
client needs: 2xx via context-manager, 4xx/5xx via `HTTPError` (has
`.code` and `.reason`), DNS/connect fail via `URLError`, deadline via
`TimeoutError`. Zero new supply-chain surface on the Pi.

**urllib Request.header_items() capitalizes header names.**
Urllib normalizes header names when you read them back — `'X-API-Key'`
becomes `'X-api-key'`, `'Content-Type'` becomes `'Content-type'`. Test
assertions on headers need to match the urllib-normalized form or use
`.casefold()` comparisons. Caught in the US-149 payload-shape test.

**Bool-vs-int guard for numeric config fields.**
`isinstance(True, int)` is `True` in Python, so a stray JSON `true`/
`false` in a numeric field silently becomes `1` / `0`. For
`syncTimeoutSeconds=true`, that's a 1-second timeout. Explicit guard in
validators:
```python
if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
    raise ConfigValidationError(...)
```
The bool check MUST come FIRST. Applied in
`src/common/config/validator.py::_validateCompanionService` (US-151).

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-04-18 | Rex (Ralph) | Added Pi HTTP Sync Client section — failed-push HWM-preserve idiom, 4xx-except-429 fail-immediate classifier, httpOpener+sleep injection seams, urllib is enough, header-capitalization quirk, bool-vs-int numeric guard (from US-149 + US-151 Sessions 48/49) |
| 2026-04-18 | Rex (Ralph) | Added US-184 caveat to the Pi 5 EXT5V pattern — the X1209 regulates the rail so EXT5V is NOT a valid source signal on this HAT; use VCELL-trend + CRATE (see progress.txt). Retained the EXT5V pattern for unregulated HATs (with a "verify via unplug drill" note) |
| 2026-04-18 | Rex (Ralph) | Added Pi 5 PMIC EXT5V_V via vcgencmd pattern for AC-vs-battery detection when a HAT has no sense pin (from US-180 Session 44 — MAX17048 rewrite) |
| 2026-04-17 | Rex (Ralph) | Added drive-detection session-lifecycle gotchas, simulator scenario quirks, and the `tests/pi/` package layout convention (from US-177) |
| 2026-04-17 | Rex (Ralph) | Added systemd service patterns (venv/install-path decoupling, journald over on-disk logs, grep-acceptance gotcha) from US-179 |
| 2026-04-17 | Rex (Ralph) | Added MAX17048 big-endian byte-swap pattern, register map, and chip-fingerprint-via-VERSION-and-CONFIG pattern (from US-180 Session 41 — filed BL-005/TD-016) |
| 2026-04-18 | Rex (Ralph) | Added pytest platform/optional-dep gates (collect_ignore_glob + pi_only marker) and Windows Store Python cold-start + adafruit_rgb_display 3.13 flake patterns (from US-182 Session 42) |
| 2026-02-05 | Ralph | Added golden code patterns from specs/golden_code_sample.py (Protocol interfaces, DI, slots dataclasses, atomic writes, deterministic main, etc.) |
| 2026-02-05 | Ralph | Added CIO development rules (strict story focus, never guess, outcome testing, reusable code, PM stitching), new spec references, git restore pattern |
| 2026-01-29 | Ralph | Added git branching strategy, PM communication protocol, housekeeping patterns, and lessons learned |
| 2026-01-26 | Knowledge Update | Added Raspberry Pi hardware patterns: I2C communication, GPIO/gpiozero, pygame display, logging, system telemetry, destructor safety, HardwareManager integration order |
| 2026-01-26 | Knowledge Update | Added threading patterns: clean interruption with Event.wait(), exception-safe polling callbacks |
| 2026-01-22 | Knowledge Update | Added module refactoring patterns (structure, backward compat, test patches, circular imports, name collisions) |
| 2026-01-22 | Knowledge Update | Added simulator patterns (CLI flag, keyboard input, transitions, auto gear), test debugging tips |
| 2026-01-22 | Knowledge Update | Added VIN decoding, database, Ollama, state machine, hardware, display, export, profile, calibration, and text similarity patterns |
| 2026-01-31 | Knowledge Update | Added Pi 5 deployment context, path resolution patterns, OSOYOO HDMI display guidance, git branch note |
| 2026-01-21 | M. Cornelison | Added operational tips section with learnings from adMonitor implementation |
