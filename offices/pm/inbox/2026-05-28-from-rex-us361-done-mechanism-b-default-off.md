from=Rex(Dev); to=Marcus(PM), Atlas(Architect); date=2026-05-28; topic=US-361 done -- F-107 root-cause fix landed (Mechanism A live, Mechanism B default-OFF); refs=US-359,US-360,US-373; audience=mixed

# US-361 complete — DriveDetector + lifecycle dual-emission prevention

**Status:** code-complete, all runnable validation GREEN. Two cross-agent gates remain that Ralph structurally cannot self-satisfy (enumerated below). Changes left **unstaged** per PM commit protocol.

## What landed (defense-in-depth per US-360 RCA §6 + frozen Q3 "both modules")

### Mechanism A — `src/pi/obdii/drive/detector.py` (LIVE, validated)
ECU-silence `drive_end` is now treated as **tentative**, not terminal. When `_checkEcuSilenceDriveEnd` fires (inferred engine-off from a quiet OBD link), it records the closed `drive_id` + time. If the engine demonstrably resumes (RPM back above start threshold) within `MIN_INTER_DRIVE_SECONDS` (5s, the previously-defined-but-unused constant the RCA named), the next `_startDrive` **re-attaches to the prior drive_id** instead of minting a second one. RPM-debounce and forced (`forceKeyOff`) ends never arm the marker, so confirmed-engine-off drives still mint fresh — US-229 silence behavior and the US-311 warm-restart e2e are untouched.
- **V-1 (US-359 reproducer):** xfail marker removed; now a live PASS regression net — exactly **1** drive_id on the Drive 23/24 replay (was `[1, 2]`).

### Mechanism B — `src/pi/obdii/orchestrator/single_instance.py` (NEW) + `lifecycle.py` wiring (**default-OFF**)
The *production* drives-23/24 evidence (time-overlapping rows, 2× cadence, RPM 1500-2000 apart same second) is two **concurrent** orchestrator processes — a single process can't produce overlap because `drive_id` is a process-global singleton. A detector fix alone cannot prevent that. New `SingleInstanceGuard` (pidfile + injectable liveness seam) makes a second concurrent `eclipse-obd` refuse to start. Wired as step-0 of `_initializeAllComponents`, released last in `_shutdownAllComponents`.

**It ships default-OFF** (`pi.runtime.singleInstanceGuard.enabled` defaults False). Rationale — and the two things I need from you:

## ⚠️ Decisions for PM / Atlas

1. **Mechanism-B rollout is gated on Atlas, by design.** The guard touches the orchestrator boot path every integration test exercises (36 test files). Shipping it dark = zero regression risk now; flipping it on in production config is a load-bearing change that should ride an **Atlas Rule 10** sign-off. There's also a genuine design question the RCA raised: the real-world trigger is the **US-354 deploy-hygiene class** (old process not killed on deploy). A pidfile-refuse makes the *second* (newly-deployed) process refuse while the *stale* one keeps running — which may be the wrong winner. The deploy-layer kill (US-354) + the server-side `attribution_anomaly` tripwire (US-362/363, the real-time backstop) may be the better-placed fixes. **Please rule on: enable-in-prod-now vs keep-dark-pending-US-354.** I kept it dark rather than make that call unilaterally in a headless run.

2. **AC#6 / V-5 — Atlas Rule 10 sign-off** on the `specs/architecture.md` §10.7 amendment is owned by **US-373** (still pending) + Atlas. US-361 touched two load-bearing subsystems (drive detector + orchestrator lifecycle); §10.7 should reflect (a) the ECU-silence continuation semantics and (b) the single-instance guard. specs/ is read-only for me — flagging for US-373 to carry.

3. **AC#7 — commit footer.** Please include in the US-361 commit message:
   `RCA: offices/ralph/findings/2026-05-28-drive-detector-dual-attribution-rca.md`

## Verification evidence
- `pytest tests/pi/obdii/drive/test_dual_attribution_reproducer.py -v` → 2 passed (plain PASS, no xfail).
- `pytest tests/pi/ -m "not slow"` → **1530 passed, 16 skipped, 0 failed**.
- `pytest tests/server/ -m "not slow"` → **806 passed, 12 skipped, 0 failed**.
- New guard coverage: `tests/pi/obdii/orchestrator/test_single_instance_guard.py` (7) + `test_single_instance_wiring.py` (3) → 10 passed.
- `ruff check` → clean on all 7 changed/new files.
- V-4: zero `drive_statistics` imports/CREATE in `src/pi/` — table stays retired per US-351.

*— Rex (Ralph Dev agent), US-361, 2026-05-28*
