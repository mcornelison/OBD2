# RCA: Drive 23/24 Dual-Attribution — DriveDetector Pi-Side Defect (US-360 / F-107)

**Date**: 2026-05-28
**Author**: Rex (Ralph Dev agent), Session for US-360
**Story**: US-360 (F-107, Sprint 43 / V0.28.0) — research/RCA
**Severity**: High (data-integrity in deployed pipeline)
**Cross-links**:
- Atlas finding (architectural record + production evidence): `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md`
- Reproducer harness (US-359): `tests/pi/obdii/drive/test_dual_attribution_reproducer.py`
- Watch List A-9 (Atlas charter §8)
**Feeds**: US-361 (root-cause fix), US-362/363/364 (server-side tripwire + backfill)

> **US-361 commit footer should reference this file**:
> `RCA: offices/ralph/findings/2026-05-28-drive-detector-dual-attribution-rca.md`

---

## 0. TL;DR (for the US-361 implementer)

1. **US-351's revert is EXONERATED as the cause.** The git diff from the
   pre-US-348 baseline (`77026b5`) to the V0.27.17 tip (`d6ad871`) on
   `detector.py` is **+53 lines, 0 deletions — every one a comment, docstring,
   or mod-history entry.** Zero executable-logic change. At the logic level the
   US-349-add → US-351-remove round trip is **byte-identical to pre-US-349**.
   The defect is **pre-existing latent**, not introduced by the revert.
2. **Defect classification (per US-360 AC#4): `byte-identical-residual` — the
   "race" is split across two distinct mechanisms** (§4). Naming it a single
   "residual race" understates it; see the precise breakdown below.
3. **There are TWO mechanisms, and they are NOT the same bug:**
   - **Mechanism A — single-process sequential split** (what the US-359
     reproducer models): an ECU-silence `drive_end` fires *mid-leg* during an
     OBD dropout, then — with **no inter-drive continuation guard** — a second
     `_startDrive` mints a new id for the *same* physical leg. Produces two
     **sequential, non-overlapping** drive_ids. **Fix target: `detector.py`.**
   - **Mechanism B — two concurrent orchestrator processes** (what Atlas's
     production evidence actually shows: time-**overlapping** rows, RPM
     1500–2000 apart in the same wall-clock second, ~2× sample cadence). A
     single process **cannot** produce overlapping attribution because
     `drive_id` is a **process-global singleton** (`drive_id.py:265`). Overlap
     ⇒ two processes, each with its own detector + its own singleton, both
     minting from the shared `drive_counter` table. **Fix target:
     orchestrator/`lifecycle.py` (single-instance enforcement) + the
     server-side tripwire, which a Pi-detector fix alone cannot prevent.**
4. **Recommended US-361 scope: BOTH `detector.py` AND
   `orchestrator/lifecycle.py`** (consistent with the frozen Q3 ruling
   "both modules in scope; behavioral test"). Defense-in-depth: close
   Mechanism A in the detector *and* prevent Mechanism B at the orchestrator,
   with the server tripwire (US-362/363) as the backstop for any residual
   Mechanism-B occurrence.

---

## 1. Reproduction status

The defect is **reproduced deterministically** by US-359
(`tests/pi/obdii/drive/test_dual_attribution_reproducer.py`,
`test_drive2324Replay_emitsExactlyOneDriveId_singlePhysicalLeg`), currently
shipping RED-as-`xfail(strict)`: the single-physical-leg replay yields **2**
distinct drive_ids where a correct detector yields 1. Run with `--runxfail` to
observe the literal assertion `DriveDetector emitted 2 drive_ids ([1, 2])`.

That harness reproduces **Mechanism A** (single-process sequential split). It
does **not** reproduce **Mechanism B** (concurrent processes) — and §4
explains why the production drives-23/24 evidence is in fact Mechanism B, a
point the harness's own docstring flags via the synthetic-derivation
conditionalOutcome (raw Drive 23/24 telemetry was not on the dev box).

---

## 2. Git archaeology (US-360 AC#2 — diff invocation + interpretation)

### Commits on the dual-emission surface

| Commit | Sprint / Version | Touch to `detector.py` / `lifecycle.py` |
|--------|------------------|------------------------------------------|
| `77026b5` | Sprint 31 / V0.27.5 | last touch of `detector.py` **before** Sprint 40 (= pre-US-348/349 baseline) |
| `b26344e` | Sprint 40 / V0.27.16 | integrate US-348 + US-349 (US-349 **adds** `DriveStatisticsRecorder` wiring) |
| `d6ad871` | Sprint 41 / V0.27.17 | US-351 **removes** the US-349 wiring (the "revert") — **V0.27.17 tip** |
| `HEAD` (`sprint/sprint43-V0.28.0`) | V0.28.0 | `detector.py` **byte-identical to `d6ad871`** (chain-merge did not alter it) |

### Diff command (AC#2) and result

```bash
# Headline diff: pre-US-348 baseline -> V0.27.17 tip
git diff 77026b5 d6ad871 -- src/pi/obdii/drive/detector.py
#   => 1 file changed, 53 insertions(+), 0 deletions(-)
#      ALL 53 lines are mod-history header + docstring + one inline comment.
#      ZERO executable-logic lines changed.

# Byte-identical (logic) test — US-349 add -> US-351 remove round-trip,
# ignoring whitespace/blank lines, filtering comments & docstrings:
git diff -w --ignore-blank-lines b729a5c d6ad871 \
    -- src/pi/obdii/orchestrator/lifecycle.py src/pi/obdii/drive/detector.py
#   => only docstring/comment text remains; no executable line added or removed.

# Dispatched branch still matches the analyzed tip:
git diff --quiet HEAD d6ad871 -- src/pi/obdii/drive/detector.py
#   => IDENTICAL (exit 0)
```

**Interpretation.** US-349 added (and US-351 removed) only the
`drive_statistics` *writer* wiring — `driveStatisticsRecorder` kwarg/setter,
`_recordDriveStatistics()` helper, its `_endDrive` call site, and in
`lifecycle.py` the `_initializeDriveStatisticsRecorder` hook. None of that
machinery touches drive **start/stop detection**, the **ECU-silence drive_end
path**, the **drive_id mint**, or any **continuation guard**. The round trip is
logic-neutral. The `lifecycle.py` range diff (`77026b5→d6ad871`,
−439/+223) looks large but that delta is dominated by **unrelated** power-watch
refactors that landed between Sprint 31 and Sprint 41 (`b729a5c` SS-T4 bridge,
`9adb0fb` ladder delete, `30baab1` T10 startup-log cutover) — *not* the
dual-attribution surface; the drive-detection lifecycle path
(`_initializeDriveDetector` @ `lifecycle.py:1349`, drive callbacks) was **not
modified by US-348/349/351 at all.**

---

## 3. Mechanism A — single-process sequential split (the reproducer's path)

This is a genuine latent defect in `detector.py`, present since the
**US-229 ECU-silence drive_end** path landed (2026-04-23), entirely
independent of US-348/349/351.

**Step-by-step (file:line, `src/pi/obdii/drive/detector.py`):**

1. Engine running → drive #1 confirmed and id minted: `_startDrive`
   (`detector.py:692`) → `_openDriveId` (`detector.py:703`, `detector.py:1131`)
   → `setCurrentDriveId(newId)`.
2. Mid-leg, the OBD/Bluetooth link drops. No ECU (Mode 01) PID arrives, so
   `_lastEcuReadingTime` stops advancing (`detector.py:530-531`), but the
   adapter-level `ELM_VOLTAGE`/`BATTERY_V` heartbeat keeps `processValue`
   ticking (`detector.py:506`).
3. After ≥ `driveEndDurationSeconds` (60 s) of ECU silence,
   **`_checkEcuSilenceDriveEnd` (`detector.py:899-947`, called at
   `detector.py:554`) fires `drive_end`** even though the engine never
   stopped. This is US-229 doing its job — but on a leg that did not actually
   end. `_endDrive` clears the singleton (`_closeDriveId`, `detector.py:825`).
4. The link recovers; RPM resumes above threshold. With state back at
   `STOPPED`, `_processRpmValue` runs `STOPPED→STARTING→RUNNING`
   (`detector.py:616-637`) and after `driveStartDurationSeconds` (10 s) calls
   `_startDrive` again → **a second id is minted for the same physical leg.**
5. **The missing guard:** `MIN_INTER_DRIVE_SECONDS = 5` (`types.py:54`) is
   defined and exported (`drive/__init__.py:70,92`) but **never referenced in
   `detector.py`**. Nothing rejects/merges a fresh drive that begins moments
   after a (false) drive_end. There is no "time since last drive_end" or
   "engine never actually stopped" continuation check.

**Signature:** two **sequential, non-overlapping** drive_ids (drive #1 ends,
*then* drive #2 begins). This matches the reproducer's `connection_log`
result `[1, 2]`.

---

## 4. Mechanism B — two concurrent orchestrator processes (the production reality)

### Why a single process cannot explain the production evidence

`drive_id` is held in a **module-level (process-global) singleton**:
`_currentDriveId` at `src/pi/obdii/drive_id.py:265`, guarded by a module-level
`Lock` (`drive_id.py:266`). The docstring (`drive_id.py:259-263`) is explicit:
the collector is single-threaded and "*a future multi-threaded refactor will
not silently split drive_id across readers and writers*." **At any instant,
within one process, there is exactly one active drive_id.** Once a second
`_startDrive` calls `setCurrentDriveId(24)`, *all* subsequent rows are tagged
24 — none are tagged 23. A single process therefore produces **sequential**
attribution and **cannot** interleave 23/24 in the same wall-clock window.

### What Atlas's production evidence shows (from the 2026-05-22 finding)

- `realtime_data` rows for drives **23 and 24 interleave across the same
  window** (e.g. 14:43:44 drive 23 @ 1339 RPM, 14:43:45 drive 24 @ 3140 RPM;
  14:47:12 *same second* both 23 @ 871 and 24 @ 2574).
- RPM values differ by 1500–2000 in the **same wall-clock second** —
  impossible for one physical engine sampled once.
- Combined cadence in the overlap window is **~2× normal** (1 / 1.55 s vs
  normal 1 / 2.4 s).
- Server-side and Pi-side overlap scans **agree**: exactly ONE overlapping
  pair (23, 24) across all 14 attributed drives; live Drive 25 is
  single-attribution clean.

Two independent sample streams at 2× cadence, each with its own monotonic
drive_id, both reading the one OBD link, time-overlapping ⇒ **two concurrent
emitter processes**, each with its own DriveDetector and its own process-global
`_currentDriveId`, both minting from the shared `drive_counter` SQLite table
(`drive_id.py:211-231`, `nextDriveId`). Process A drew 23, process B drew 24.

### Where Mechanism B is (not) guarded

- `lifecycle.py` constructs exactly **one** `_driveDetector` per orchestrator
  instance (`_initializeDriveDetector` @ `lifecycle.py:1349`,
  `_shutdownDriveDetector` @ `lifecycle.py:2139`). That is correct *within* a
  process.
- **There is no cross-process single-instance guard** anywhere in the
  orchestrator/lifecycle path — no pidfile, no `flock`, no "already running"
  check (grep for `pidfile|flock|single.instance|already.running` over
  `lifecycle.py` returns nothing). Nothing prevents two `eclipse-obd`
  orchestrator processes from running concurrently.
- **Plausible trigger (deploy-hygiene class):** this is the same family as
  **US-354** (V0.27.16 deploy wrote files + bumped `.deploy-version` but did
  **not** restart `eclipse-obd` / `daemon-reload` — the old code kept running
  in memory). A deploy/restart that leaves the prior orchestrator alive while a
  new one starts, or any double-spawn, yields exactly the observed signature.
  Drive 25 being clean is consistent with the second process having exited by
  then (transient/edge-case, not always-on — matches Atlas's bounding scan).

> **Evidence boundary (per US-360 conditionalOutcome).** Raw Drive 23/24
> per-process telemetry (e.g. journald PID census across the 23→24 window) was
> not available on the dev box for this RCA; Mechanism B is inferred from the
> process-global-singleton invariant + Atlas's overlap/cadence evidence. If
> chi-eclipse-01 journald for 2026-05-22 14:43–14:47 is recoverable, a PID
> census across the window would confirm/deny two `eclipse-obd` PIDs directly
> and is the recommended IRL confirmation step.

---

## 5. Defect classification (US-360 AC#4)

**Category: `byte-identical-residual-race`** — selected, with this precision:

- The **revert was byte-identical (logic-level)**: §2 proves the US-349→US-351
  round trip changed only comments/docstrings; the V0.27.17 tip is
  logic-identical to the pre-US-349 baseline, and HEAD matches that tip.
- The **residual** is *not* a within-detector thread race. It is two
  pre-existing conditions the revert neither introduced nor removed:
  - **A (deterministic state-machine gap):** ECU-silence `drive_end` mid-leg
    + missing `MIN_INTER_DRIVE_SECONDS` continuation guard. Fully
    deterministic (the reproducer has no threading/`time.sleep`).
  - **B (inter-process multiplicity / race):** two concurrent orchestrator
    processes minting from the shared `drive_counter`. This *is* a genuine
    race, but an **inter-process** one — orthogonal to detector logic and
    invisible to a single-process unit test.

Explicitly **NOT** `upstream-V0.27.16-timing-shift`: no timing/threshold/logic
changed in `detector.py` across V0.27.16↔V0.27.17 (the diff is comment-only).
Explicitly **NOT** `non-byte-identical-delta`: there is no logic delta to
enumerate.

---

## 6. Recommendation to US-361 (fix target + scope)

Per US-360 conditionalOutcomes and the frozen **Q3 ruling** ("both modules in
scope; behavioral test, not file-path test"), recommend **defense-in-depth
across both modules**:

1. **`src/pi/obdii/drive/detector.py` — close Mechanism A.** Wire a
   continuation guard so a `drive_end` driven by ECU-silence (engine never
   confirmed stopped) does not allow an immediate fresh mint for the same leg.
   Options for the implementer (US-361 decides HOW):
   - Use `MIN_INTER_DRIVE_SECONDS` (`types.py:54`) as a real debounce in
     `_startDrive`/`_processRpmValue` (reject a new start within N s of the
     last `drive_end`), **and/or**
   - Distinguish a *true* engine-off `drive_end` (sustained RPM=0 debounce)
     from an *ECU-silence* `drive_end` (link dropout) and treat the latter as a
     **pause/continuation** of the open drive rather than a terminal end — so a
     mid-leg OBD blackout reattaches to the same drive_id instead of minting a
     new one.
   - **Behavioral acceptance:** the US-359 reproducer (xfail removed) asserts
     exactly **1** drive_id. Keep `tests/pi/ -m "not slow"` green.
2. **`src/pi/obdii/orchestrator/lifecycle.py` (and/or service layer) — prevent
   Mechanism B.** Add a single-instance guard for the orchestrator (pidfile /
   `flock` / "already running → exit" check) so a second `eclipse-obd` process
   cannot run concurrently and double-mint. This is the structural fix for the
   *observed* drives-23/24 evidence; the detector fix alone cannot prevent it
   (a second process has its own detector + its own singleton).
3. **Server-side tripwire (US-362/363/364) is the backstop.** Because
   Mechanism B is an inter-process condition that can recur from deploy
   hygiene, `detect_overlapping_drives` + `data_quality='attribution_anomaly'`
   is the only thing that *catches* a residual occurrence after the fact. The
   Pi fix reduces the probability; the server tripwire makes any residual
   occurrence observable. Both are needed; neither is sufficient alone.

---

## 7. Evidence index

| Claim | Evidence |
|-------|----------|
| Revert is logic-byte-identical | `git diff 77026b5 d6ad871 -- detector.py` = +53/-0, all comments/docstrings (§2) |
| HEAD == analyzed tip | `git diff --quiet HEAD d6ad871 -- detector.py` exit 0 (§2) |
| US-349/US-351 round-trip logic-neutral | `git diff -w --ignore-blank-lines b729a5c d6ad871 -- lifecycle.py detector.py` (only docstring text) |
| ECU-silence drive_end fires mid-leg | `detector.py:899-947` (`_checkEcuSilenceDriveEnd`), called `detector.py:554` |
| No continuation guard | `MIN_INTER_DRIVE_SECONDS` (`types.py:54`) unreferenced in `detector.py` (grep §confirmed) |
| Second mint path | `_startDrive` `detector.py:692`, `_openDriveId` `detector.py:703/1131` |
| drive_id is process-global singleton | `drive_id.py:265-266`, docstring `drive_id.py:259-263` |
| Shared monotonic counter | `nextDriveId` `drive_id.py:211-231`, `drive_counter` table |
| Single detector per orchestrator, no inter-process guard | `lifecycle.py:1349`, grep `pidfile|flock|single.instance` = none |
| Production overlap/cadence evidence | Atlas finding `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md` §2 |
| Reproducer (Mechanism A) | `tests/pi/obdii/drive/test_dual_attribution_reproducer.py` |

---

*— Rex (Ralph Dev agent), US-360, 2026-05-28*
