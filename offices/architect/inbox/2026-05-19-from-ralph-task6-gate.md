From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 6 complete. Design-gate requested.**

Hard Protocol rename + single explicit registry seam — one commit, scope-fenced.

## Task #
**Task 6** — Formalize the `ShutdownTask` Protocol (renamed from `PipelineTask`)
+ the V1 `buildV1Tasks(syncTask)` single-task registry seam.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`94b7fd8`** (6 files, +101/-20):

- `src/pi/power/power_watch/contract.py` — `class PipelineTask(Protocol)` →
  `@runtime_checkable class ShutdownTask(Protocol)`; `__all__` updated;
  docstring + mod-history row.
- `src/pi/power/power_watch/pipeline.py` — import + `list[ShutdownTask]` type
  annotation + docstring updated.
- `src/pi/power/power_watch/tasks/sync_with_server.py` — header + class
  docstring updated.
- `src/pi/power/power_watch/__main__.py` — added module-level
  `buildV1Tasks(syncTask) -> list` with full docstring; both production +
  `PW_TEST_ONESHOT` `runPipeline` call sites now flow through it.
- `tests/pi/power/power_watch/test_task_seam.py` (NEW) — Step 1 seam test
  asserting `isinstance(syncTask, ShutdownTask)`, `hasattr(m, "buildV1Tasks")`,
  and `buildV1Tasks(syncTask) == [syncTask]` (exactly one task, Option A).
- `tests/pi/power/power_watch/test_contract.py` — import updated;
  structural-conformance test renamed; new `isinstance` assertion exercising
  the runtime-checkable Protocol.

## Pre-registered gate criteria — evidence

**#1 — TDD red→green:**
- RED: `pytest tests/pi/power/power_watch/test_task_seam.py -q`
  → `ImportError: cannot import name 'ShutdownTask'` (right reason).
- GREEN: after rename + seam → **1 passed**. Powerwatch suite **23 passed**
  (was 22; seam test added).

**#2 — Protocol name rename clean, no half-rename:**
```
$ rg -n "\bPipelineTask\b" src/ tests/
src/pi/power/power_watch/tasks/sync_with_server.py:8: # (renamed from PipelineTask in SS-T6).
src/pi/power/power_watch/contract.py:15:  # 2026-05-17 Initial -- PipelineTask protocol.
src/pi/power/power_watch/contract.py:16:  # 2026-05-19 SS-T6 Hard rename PipelineTask -> ShutdownTask
src/pi/power/power_watch/contract.py:53:  # ``PipelineTask`` in SS-T6 to match the ShutdownSequencer vocabulary.
tests/pi/power/power_watch/test_contract.py:14:  # 2026-05-19 SS-T6 Rename PipelineTask -> ShutdownTask
```
5 hits, **all in mod-history rows or class docstrings documenting the rename**.
**ZERO live code references** anywhere — class def, importers, type annotations,
tests, `__all__` — all consume `ShutdownTask`. Hard rename per the T2-alias
discipline (no alias needed; consumers updated in the same commit).

**#3 — `buildV1Tasks` seam in `__main__.py`:**
- Defined at module level (line ~115) with the docstring documenting it as
  the **SINGLE EDIT POINT** for future plugin tasks: "a new task appends
  here and that is the ONLY production change. `ShutdownSequencer` and
  `runPipeline` are untouched when new tasks land."
- V1 returns exactly `[syncTask]` (Option A scope, locked).
- Both production (`main()` line ~234) AND `PW_TEST_ONESHOT` (line ~156)
  `runPipeline` call sites flow through `buildV1Tasks(syncTask)`.
- Tested: `assert len(buildV1Tasks(t)) == 1` (criterion #3 evidence by test,
  not inspection).

**#4 — Scope fence:** the 6 files in `94b7fd8` are exactly `contract.py` +
`pipeline.py` + `tasks/sync_with_server.py` + `__main__.py` + the new seam
test + the contract test. `controller.py` / `lifecycle.py` /
`power_source_provider.py` / `pld_sensor.py` UNTOUCHED (settled).

**#5 — No-broken-intermediate:**
- `pytest tests/pi/power/power_watch/ -m "not slow"` → **23 passed**.
- `pytest tests/pi/hardware/ tests/pi/power/ tests/pi/orchestrator/ tests/test_config_validator.py -m "not slow"` → **362 passed, 4 skipped, 0 failed**.
- `python validate_config.py` → **exit 0**.
- `python -m ruff check` on 6 touched files → "All checks passed!"

**#6 — SSOT discipline (hard rename, no alias):** same commit updates all
importers (`pipeline.py`, `sync_with_server.py`, `__main__.py`, `test_contract.py`)
+ the Protocol def + `__all__`. No cross-task consumer-ordering hazard exists
for an internal Protocol-name rename, so no T2-class alias was needed -- and
none was added. One name per fact, immediately.

## Small plan-defect disclosure (same class as the SS-T3 `_FakePld` fix)
The plan Step 1 test asserts `isinstance(t, ShutdownTask)`. A `Protocol` is
**not** runtime-checkable by default — `isinstance` raises
`TypeError: Instance and class checks can only be used with @runtime_checkable
protocols`. I added `@runtime_checkable` to the `ShutdownTask` Protocol so the
plan's `isinstance` assertion works for the right reason (the class actually
satisfies the Protocol structurally — `name: str`, `run() -> OutcomeKind`),
not by accident. This is a strict superset of behavior: the static structural
check still works (the existing mypy/pyright `task: ShutdownTask = _DummyTask()`
remains valid), AND consumers can verify membership at runtime — which is
precisely what a documented plugin seam needs. **Disclosed before the gate,
not at it** (Task-2 lesson applied). Marcus FYI: a tiny plan-of-record
correction is worthwhile so the literal `@runtime_checkable` is in the
authoritative text.

## Design invariants preserved
- **SSOT for the Protocol name:** one name (`ShutdownTask`) at one definition
  site (`contract.py`); all consumers import from there.
- **Single edit point for future plugins:** `buildV1Tasks` is the ONLY
  production path that needs editing when a new task lands (proved by the
  seam test); `ShutdownSequencer` and `runPipeline` are untouched.
- **Scope-fence honored:** controller/lifecycle/provider/sensor all
  untouched (settled in T3/T4/T5).

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 7
(the systemd-parity orchestration-proof test — the V0.27.12-DOA net, highest-
value gate of the chain). — Ralph
