# Testing Patterns

Load on demand when writing tests, fixtures, or platform-gated test infrastructure.

## Mocking and Testing

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

---

## Windows-Specific

**CSV file handling**
Always use `newline=''` parameter when opening CSV files to prevent extra blank lines on Windows. See `specs/anti-patterns.md` for details.

**Path handling in tests**
Use `os.path.join()` for path assertions to work on both Windows and Unix. See `specs/anti-patterns.md` for details.

---

## Test Debugging

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

---

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

---

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

---

## Deterministic SQLite Fixtures (Pi-Run)

**Bit-for-bit reproducible fixtures need VACUUM + sorted sqlite_sequence +
no wall-clock + closed-form values.** US-191's `scripts/seed_pi_fixture.py`
produces SHA256-stable `.db` files that can be checked into git and
depended on by exact-count assertions. The recipe:

1. **Pure closed-form value synthesis** — never use `random`, not even
   seeded. `math.sin(2*pi*sampleIdx/period + 0.37*driveIdx)` is stable
   across Python versions; `random.Random(42)` is not (algorithm drift
   between major releases has bitten us in other projects). Round to a
   fixed precision (`round(x, 2)`) so float printf representation is
   platform-stable.
2. **No wall-clock anywhere** — `datetime.now()` obviously not, but also
   beware `DEFAULT CURRENT_TIMESTAMP` on `created_at`/`updated_at`
   columns. Override in the INSERT with a constant `_BASE_ISO`.
3. **Sort sqlite_sequence after inserts** — SQLite's planner may reorder
   executemany() batches, which changes the internal `sqlite_sequence`
   physical layout. After all inserts, run
   `DELETE FROM sqlite_sequence; INSERT INTO sqlite_sequence(name, seq)
    SELECT name, seq FROM <buffer> ORDER BY name`.
4. **VACUUM at the end** — without it, two runs with the same logical
   data can produce different free-page layouts. `conn.execute("VACUUM")`
   compacts the file to a canonical form.

Tests verify reproducibility with
`hashlib.sha256(path.read_bytes()).hexdigest()` comparison after two
back-to-back builds. Pattern at
`scripts/seed_pi_fixture.py::buildFixture` (US-191). Reusable for any
test fixture that must diff cleanly in PR review.

**Multi-table fixtures for iterators over a registry**: when the
consumer (SyncClient, sync_now.py --dry-run) iterates a table registry
like `sync_log.IN_SCOPE_TABLES`, the fixture must include EVERY table
in the registry — empty placeholders for unused tables are fine (cost
~50 bytes each). Apply `ALL_SCHEMAS` + `ALL_INDEXES` wholesale from
the canonical schema module rather than cherry-picking — adding a new
table to the registry then forces a fixture-regen, which is the right
signal. Live at `scripts/seed_pi_fixture.py::_createSchema` (US-191).

---

## Bash Driver Testing from Pytest (Pi-Run)

**Test bash drivers from the Python test suite via subprocess.run +
`--dry-run` flag + `_skipWithoutBash` skip marker.** The full
`pytest tests/` run on Windows + CI catches regressions in shell
drivers without anyone plugging in the target hardware. Pattern at
`tests/scripts/test_replay_pi_fixture_sh.py` (US-191):

- `_BASH_PATH = shutil.which("bash")` + class-level
  `@pytest.mark.skipif(_BASH_PATH is None, reason="...")` so the class
  collects-and-skips cleanly if bash ever vanishes from PATH rather
  than erroring collection.
- `subprocess.run([_BASH_PATH, str(driver), *args],
                  capture_output=True, text=True, timeout=60)` — bash
  cold-start is cheap (unlike Windows Store Python's ~30s cold-start),
  60s is plenty even under full-suite CPU saturation.
- Drive behavior branches with `--dry-run` so no SSH / SCP / production
  actions happen. The driver prints `[dry-run] ssh ...` markers instead
  of calling the real binary.
- Assertion shapes: exit-code tests (`result.returncode == 0/1/2`),
  stdout-contains (help text, dry-run markers), stderr-contains (error
  paths), and a step-ordering walk that advances a cursor through
  `result.stdout` with `stdout.find(nextHeader, cursor)` so a missing
  OR reordered step fails loudly.
- Exercise every flag path at least once: `--help`, `-h`, the default
  positional, the `--flag value` alternative, error-on-duplicate, and
  the "skip/no-op" short-circuit flags.

**ruff does NOT lint `.sh` files** — running `ruff check scripts/foo.sh`
produces cascading syntax errors because ruff parses by extension.
Invoke ruff on directories (`ruff check src/ tests/`) or explicit
Python paths, never explicit `.sh` paths. For bash-specific lint, add
shellcheck to the pipeline (not yet in `make lint` as of US-191).
