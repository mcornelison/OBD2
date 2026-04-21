# OBD + Data Flow Patterns

Load on demand when working on OBD polling, drive detection, simulator, database writes, or VIN decoding.

## State Machine Patterns

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

---

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

---

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

---

## Simulator Patterns

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

---

## Database Patterns

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

---

## VIN Decoding

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

---

## Text Similarity

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
