# US-386 reproducer shipped — Root-2 scope boundary (for US-387 RCA + US-388 fix)

from=Rex(Dev); to=Marcus(PM), Atlas(Architect); date=2026-06-28; topic=US-386 reproducer scope; audience=mixed; refs=US-386,US-387,US-388,US-389,US-390

**US-386 done** (`passes:true`). Reproducer: `tests/pi/obdii/drive/test_drive2829_close_signal_reproducer.py` (reuses the US-359 InjectedClock harness; deterministic, no wall-clock, **no comms events** per contract — a "missed close" = readings stop before the 60s debounce completes, with no heartbeat to drive the ECU-silence path).

## The decision you should sanity-check

The `conditionalOutcome` ("escalate to Atlas if it won't reproduce at the detector unit level") **did NOT fire** — the substantive defect reproduces in-process. But the 28/29 signature has two halves, and only one is unit-reproducible:

- **Root 2 — stale-open / missed-close / absorption (REPRODUCED here, RED).** A drive whose close never fired stays open; a later key-on is *absorbed* into the stale session instead of minting a new `drive_id`. Both RED scenarios fail with `got=[1]` — one `drive_id` spanning two physical drives. This is the half **US-388** must fix; the reproducer is its GREEN gate.
- **Root 1 — concurrent-process *overlap* (NOT unit-reproducible, by construction).** The connection_log "overlap" (two ids open at once, ids out of temporal order) requires **two racing detector processes** against the shared `drive_counter`. A *single* in-process `DriveDetector` can never hold two simultaneously-open sessions — the only exit from `RUNNING` is `_endDrive`, which writes the matching `drive_end`. So I did **not** fake overlap in one detector (that would invent a non-real mechanism). Per Atlas's 2026-06-19 RCA, Root 1 is the concurrent-process root, mitigated out-of-band → made durable by **US-389** (single-instance guard + RuntimeDirectory matched-pair) and backstopped server-side by **US-390** (`detect_overlapping_drives`).

**Net:** the in-process harness is the Root-2 gate. The "overlap" word in the US-386 acceptance maps to Root 1, which is correctly owned by US-389/US-390, not by a detector unit test. Full Root-1/Root-2 rationale (with file:line traces) is in the reproducer's module docstring — useful raw material for **US-387's RCA**.

## Handoffs
- **US-387 (RCA):** the docstring already traces the absorption mechanism (`processValue` RUNNING/STOPPING + RPM-above-end → `belowThresholdSince=None` → continue, no mint). Render the file:line root from it.
- **US-388 (fix):** removes the two `xfail` markers (strict=False, US-359 precedent) once the fix flips both stale-open scenarios GREEN.

Flag if you'd rather I had blocked-and-escalated instead — I judged the Root-2 reproduction sufficient to keep US-387/388 buildable.
