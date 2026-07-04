from=Marcus(PM); to=Rex(Dev); date=2026-07-03; topic=DISPATCH Sprint 54/V0.29.8 -- OBD capture reliability P0 (F-117/A-17 + BL-016) + data/power hygiene (7 stories); audience=agent; urgency=high; refs=US-441,US-442,US-443,US-444,US-445,US-432,US-447

# Marcus -> Rex: Sprint 54 / V0.29.8 DISPATCHED

Branch **`sprint/sprint54-V0.29.8`** forked from `dev`, pushed, upstream set; checkout is on it. **7 stories.** Atlas-reviewed. **The Pi captures ZERO OBD rows right now** — US-441 fixes that and is the P0.

## Testing discipline (unchanged, working — keep it)
Story's **TARGETED tests SYNCHRONOUS + commit in-iteration.** No full-suite in-loop, no background-and-wait (TD-059). **All code stories: `ruff` + `mypy` (strict)** — Atlas added mypy (GAP-2).

## Design refs (build to these)
- US-441/447: `offices/architect/findings/2026-07-03-obd-capture-rca-eclipse-obd-connection-thread-race.md` (Atlas A-17 RCA)
- US-432: `offices/architect/reports/2026-07-03-bl016-us432-idle-poll-rpm-mask-fix-ruling.md` (Option B)

## Build order
1. **US-441 OBD capture race fix (F-117/A-17, P0, L, PM-signed-off)** -- **start here.** ⚠️ **The lock lives on the `ObdConnection` WRAPPER (`obd_connection.py`), NOT `lifecycle.py`** (Atlas GAP-1, load-bearing): the realtime logger reads `self.connection.obd.query()` DIRECTLY at **`logger.py:220 AND 290`**, bypassing lifecycle. ONE wrapper lock guards every `.obd` access; **ALL callers acquire it** -- lifecycle daemons, US-301 heartbeat, AND the logger reads. Epoch-fence orphaned timeout daemons. Preserve TD-036 no-boot-hang. **Real-concurrency test** = logger read path + orphaned daemon on the SAME wrapper, asserts no interleaving (fails pre-fix; a mocked-at-lifecycle test is the trap). Arch threading-model section updated in-sprint (bound to this story, A-11).
2. **US-432 idle-poll RPM-mask (BL-016 Option B; deps US-441)** -- force RPM past python-obd's dark-ECU support cache, **scoped to known-mandatory Mode-01 PIDs (RPM min), NEVER blanket**; a connection-scoped "engine-confirmed -> force" latch (set at `core.py:1205`, cleared on drive_end/disconnect) applied to the **ongoing poll AND the probe**. **Read-path ONLY** -- do NOT touch `evaluateTimeouts`/`_maybeCloseOnDeadline`/NULL-latch/`_startDrive` (US-388 stays intact).

**Independent (any order):**
3. **US-442** close the 4 historical orphan `drain_event` rows (from US-434) -- annotate, never delete.
4. **US-443** tester V0.28+ data-profile **DESIGN** items (8; distinct from US-437 bugs) -- implement ready ones, flag those needing Spool/Atlas.
5. **US-444** UpsMonitor slow-drain detection + flap-debounce.
6. **US-445** automated battery test on boot (honest-instrument -> unknown).

**Last:**
7. **US-447** doc-sync (architecture.md threading-model + regression_manifest).

## Validation = BENCH for the code + CAR DRILL for capture
US-441 + US-432 build + unit-test on the bench, but their **acceptance is the CIO's car**: a live sustained-capture drive (US-441) + cold-boot-key-OFF->engine-on (US-432) -- **one A-9 re-gate exercises both.** The mocked-connection tests pass green while the live path captures 0, so the real-concurrency test (US-441) is non-negotiable. NO bench story needs the car.

## Notes
- US-446 (drive_statistics) is NOT in this sprint -- deferred to Sprint 55 under Atlas's F-104 gate.
- Commit to THIS branch; stale index.lock = TD-057.

CIO launches `ralph.sh` from his shell.

-- Marcus
