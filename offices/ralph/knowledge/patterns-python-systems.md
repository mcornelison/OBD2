# Python + Systems Patterns

Load on demand when working on Python stdlib patterns (threading, signals, logging, paths), systemd integration, Ollama/AI, or module refactoring.

## Threading Patterns

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

---

## Configuration

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

---

## Signal Handling

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

---

## Path Resolution

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

---

## Logging Patterns

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

---

## Ollama/AI Integration

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

---

## Destructor Safety

**Check hasattr in __del__**
__del__ may be called on partially initialized objects:
```python
def __del__(self):
    if hasattr(self, '_lock') and hasattr(self, '_timer'):
        with self._lock:
            if self._timer:
                self._timer.cancel()
```

---

## Export Patterns

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

---

## Profile and Calibration

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

---

## Module Refactoring Patterns

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

## Restoring Deleted Test Files

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
