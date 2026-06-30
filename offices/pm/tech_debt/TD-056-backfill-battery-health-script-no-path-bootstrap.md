# TD-056: scripts/backfill_pi_battery_health_log_historical_drains.py has no sys.path bootstrap

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code                      |
| Affected     | `scripts/backfill_pi_battery_health_log_historical_drains.py` |
| Introduced   | Script authored without the Pi-tier entry-point path bootstrap that the sibling CLIs use |
| Created      | 2026-06-29                |

## Description

While batch-auditing Pi-side `scripts/*.py` entry points for US-397 (the
`sync_now.py` / `record_drain_test.py` ROOT-insert + `src.pi.*` import break →
`ModuleNotFoundError: No module named 'pi'`), `backfill_pi_battery_health_log_historical_drains.py`
was found to fail under the bare operator invocation
(`python scripts/backfill_pi_battery_health_log_historical_drains.py --help`)
with a **different** error:

```
ModuleNotFoundError: No module named 'src'
```

Root cause: the script imports `from src.common.time.helper import ...` and
`from src.pi.power.types import ...` at module top level (lines 119-120) but
has **no `sys.path.insert(...)` bootstrap at all** — neither the repo ROOT nor
`src/` is placed on `sys.path`. It only runs via `python -m scripts.backfill_...`
from the repo root, or with an external `PYTHONPATH` override.

This is NOT the same bug class US-397 fixed (that was "ROOT-insert + `src.pi.*`"
which resolves `src.pi.*` but leaves top-level `pi` unimportable). This script
has the opposite problem: no path bootstrap, so even `src` is unresolvable.
Per the US-397 scope fence (Refusal Rule 3) it was left untouched and recorded
here.

## Why It Was Accepted

US-397's scope was explicitly the `ROOT + src.pi.*` → `No module named 'pi'`
cluster (`sync_now.py` + `record_drain_test.py`). The backfill script's
failure is a distinct root cause (missing bootstrap), and the script is a
one-shot historical-backfill tool (not part of any routine operator or service
path), so the blast radius is low. Pulling it into US-397 would have been
scope drift ([[feedback-over-scoping]]).

## Risk If Not Addressed

Low. An operator running the script the "obvious" way
(`python scripts/backfill_pi_battery_health_log_historical_drains.py`) hits a
loud `ModuleNotFoundError: No module named 'src'` immediately — no silent data
corruption, just a friction/confusion cost. The workaround
(`python -m scripts.backfill_...` from repo root) works today.

## Remediation Plan

Add the canonical Pi-tier entry-point path bootstrap that `sync_now.py` /
`record_drain_test.py` now use (US-397):

```python
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

…before the `from src.common...` / `from src.pi...` imports. (Keep `src.common.*`
on the legacy form for exception identity per the US-397 note; the `pi.*` flip
is optional for this one-shot tool.) Add a subprocess "operator runtime" import
smoke test mirroring `tests/scripts/test_sync_now.py::TestOperatorRuntimeImport`.
A `B-` backlog item is not warranted; fold into the next scripts-hygiene pass.
