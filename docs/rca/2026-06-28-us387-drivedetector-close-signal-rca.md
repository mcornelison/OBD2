# RCA — DriveDetector close / drive-end path (drives 28/29)

| | |
|---|---|
| **Story** | US-387 (F-107, E-002) — RCA: root-cause the DriveDetector close / drive-end path |
| **Author** | Rex (Ralph / Dev) |
| **Date** | 2026-06-28 |
| **Sprint** | 47 / V0.29.1 (data-integrity hardening) |
| **Status** | DRAFT — pending Atlas review (validationCriteria gate for US-388) |
| **Refs** | A-9, F-107, US-386 reproducer, Atlas 2026-06-19 RCA ruling, Spool 2-table corroboration |
| **Reproducer** | `tests/pi/obdii/drive/test_drive2829_close_signal_reproducer.py` (US-386) |
| **Code under analysis** | `src/pi/obdii/drive/detector.py`, `src/pi/obdii/orchestrator/event_router.py`, `src/pi/obdii/drive_id.py` |

> **Scope rule (this story):** RCA only. No fix. The fix is US-388 (Root 2) and US-389/US-390
> (Root 1 closure + backstop), both build-blocked on Atlas accepting this document.

---

## 1. The observed defect

After the US-361 fix (Drive 23/24 dual-attribution), the A-9 DriveDetector defect **recurred** on
drives 28/29 (~2026-06-06). The live symptom set, from `connection_log` on the production Pi:

- **`drive_start` fired 29 times, `drive_end` only 18** → **11 drives never closed.**
- A **second `drive_id` appears open while a prior one is still open** (an *overlap*), with ids
  occasionally **out of temporal order**.

Atlas's 2026-06-19 ruling split this into two named roots; Spool's 2-table corroboration ruled out
the obvious alternative hypothesis (comms-drop). This RCA renders the exact code mechanism for each
half and maps both to the US-386 reproducer.

---

## 2. How the close signal actually works (the load-bearing fact)

**The entire drive-close state machine is tick-driven. There is no independent timer or watchdog
thread.** Every close decision is evaluated *only* inside `DriveDetector.processValue(...)`
(`detector.py:521`), and `processValue` is called from exactly one place in the running system:
the OBD reading callback `EventRouter._handleReading` (`event_router.py:404-407`):

```python
# event_router.py:404-407
if self._driveDetector is not None:
    try:
        if paramName is not None and value is not None:
            self._driveDetector.processValue(paramName, value)
```

So **if readings stop arriving, no close decision is ever evaluated.** There are exactly four ways a
drive can close, and three of the four require the tick loop to keep running:

| Close path | Code | Requires a tick after the deadline? |
|---|---|---|
| RPM-debounce (RPM≤0 for `driveEndDurationSeconds`) | `_processRpmValue` STOPPING branch, `detector.py:665-672` | **Yes** — needs a tick `≥60 s` after `belowThresholdSince` |
| ECU-silence (no Mode-01 PID for `driveEndDurationSeconds`, heartbeat still ticking) | `_checkEcuSilenceDriveEnd`, `detector.py:932-986` (called at `detector.py:569`) | **Yes** — needs a heartbeat tick to run the check |
| `forceKeyOff(reason)` (power-down) | `detector.py:1244-1284` | No (external call) — only fires in the US-216 power-imminent path |
| `stop()` (detector shutdown) | `detector.py:466-474` | No — only on clean process shutdown |

The decisive consequence: **the connection-lost handler does NOT close a drive.**
`EventRouter._handleConnectionLost` (`event_router.py:522-556`) updates display state and starts
reconnection — it never touches the DriveDetector. So when the OBD link drops (or the engine simply
stops and the data-acquisition loop runs dry), the only thing that *could* close the open drive is a
future tick that never comes.

---

## 3. Root 2 — stale-open / missed-close leak (the substantive defect; US-388)

### 3.1 Mechanism (file:line)

1. Engine off. RPM drops to 0. A tick arrives: `RUNNING → STOPPING`, `belowThresholdSince = now`
   (`detector.py:656-660`). The debounce clock starts.
2. The RPM-debounce needs **another tick at least `driveEndDurationSeconds` (60 s) later** to compute
   `elapsed` and fire `_endDrive` (`detector.py:665-672`):
   ```python
   # detector.py:665-672
   elif self._driveState == DriveState.STOPPING:
       if rpmAtOrBelowEnd:
           if self._belowThresholdSince:
               elapsed = (now - self._belowThresholdSince).total_seconds()
               if elapsed >= self._config.driveEndDurationSeconds:
                   self._endDrive()
   ```
3. **But the readings stop before 60 s elapses.** Engine-off cuts the data-acquisition loop short:
   a couple of RPM=0 ticks (≈20 s of them), then silence. No tick ever lands past the 60 s mark, so
   the `elapsed >= 60` comparison is **never evaluated**. The drive stays in `STOPPING` with a live
   session — **stale-open.**
4. The ECU-silence backstop (`_checkEcuSilenceDriveEnd`, `detector.py:932-986`) cannot save it either,
   because it *also* runs only inside `processValue`. With **no adapter heartbeat** (no `BATTERY_V`
   via `ELM_VOLTAGE` — Spool ruled out comms activity; the link is simply quiet) there is no wake-up
   tick to run the check. Silence-close needs a tick to fire and there is none.
5. **A later key-on then *continues* the stale session instead of opening a new drive.** When RPM
   crosses the start threshold again, the very first tick runs the top of `processValue` which sets
   `_lastEcuReadingTime = now` for any ECU-dependent param (RPM included) **before**
   `_checkEcuSilenceDriveEnd` runs (`detector.py:545-546`, then `:569`) — so silence can never fire
   on resume. The state machine is still in `RUNNING`/`STOPPING`, so `_processRpmValue` simply clears
   `belowThresholdSince` and transitions back to `RUNNING` (`detector.py:662-663` / `:673-677`).
   **`_startDrive` is never called, so no new `drive_id` is minted** (`_openDriveId`,
   `detector.py:1208-1242`, is only reached from `_startDrive`, `detector.py:735`). The second
   physical drive is **absorbed** into the first drive's id.

### 3.2 Why the US-361 fix does not cover this

US-361 (`_isEcuSilenceContinuation`, `detector.py:988-1019`) was built for the *opposite* timing: a
mid-drive Bluetooth dropout where an ECU-silence `drive_end` **did** fire, and a resume within
`MIN_INTER_DRIVE_SECONDS` (5 s) should *re-attach* to the same leg. That path only arms its marker
when `_checkEcuSilenceDriveEnd` actually closes a drive (`detector.py:984-986`). In the 28/29 case
the silence close **never fires** (step 4), so there is no `drive_end` at all — the failure mode is
"close never happened," which US-361 does not address. The two are complementary, not redundant.

### 3.3 This is exactly what the reproducer shows

`tests/pi/obdii/drive/test_drive2829_close_signal_reproducer.py`, run with `--runxfail`:

```
TestBackToBackMissedClose ... got [1]  (expected 2)  — second drive absorbed into id #1
TestKeyOnAfterMissedClose  ... got [1]  (expected 2)  — next-day key-on absorbed into id #1
TestShortDriveControl      ... PASS     — readings continue past 60 s → clean single close
TestReproducerDeterminism  ... PASS
```

The replay sequences (`_BACK_TO_BACK_MISSED_CLOSE_REPLAY`, lines 168-182;
`_KEY_ON_AFTER_MISSED_CLOSE_REPLAY`, lines 188-202) stop the engine-off RPM=0 ticks at **20 s**
(`< 60 s`) then resume — reproducing step 3 precisely. The GREEN control
(`_SHORT_DRIVE_REPLAY`, lines 153-161) continues key-off readings to **61 s ≥ 60 s**, so the debounce
fires and the drive closes — proving the harness is faithful and the RED is a genuine defect, not a
harness artifact.

---

## 4. Root 1 — concurrent processes (overlap; mitigated out-of-band, closed by US-389/US-390)

### 4.1 Mechanism (file:line)

The connection_log *overlap* — two `drive_id`s open at once, ids out of temporal order — is **not** a
close-signal failure. It is two `eclipse-obd` orchestrator processes running at the same time, each
with its own DriveDetector, racing the **shared** `drive_counter`:

- `nextDriveId` (`drive_id.py:211-231`) does `UPDATE drive_counter SET last_drive_id = last_drive_id + 1`
  then `SELECT`. Its own docstring warns: *"For multi-connection setups the caller should wrap in an
  explicit `BEGIN IMMEDIATE`."* — and the caller `_openDriveId` (`detector.py:1208-1242`) does **not**.
- The in-process drive context is a **per-process module-level singleton**: `_currentDriveId`
  (`drive_id.py:265`) with a per-process `threading.Lock` (`drive_id.py:266`). **Two processes have
  two independent globals.** Neither sees the other's open drive; each writes its own
  `drive_start`/`drive_end` pair to the shared `connection_log`. The result on the server is two ids
  open concurrently, minted in an order that need not match wall-clock order (process clocks +
  interleaved counter increments).

### 4.2 Why a single in-process detector can NEVER reproduce overlap

By construction, one `DriveDetector` instance holds at most one `_currentSession` (`detector.py:218`).
The only exit from `RUNNING` is `_endDrive` (`detector.py:790`), which writes the matching `drive_end`
**before** clearing the session. So a single detector cannot hold two simultaneously-open drives.
Reproducing overlap requires **two racing processes** — i.e. the real lifecycle loop, not a unit
harness. This is why US-386's `conditionalOutcome` (escalate if the defect needs the real loop) did
**not** fire: the *substantive* half (Root 2) does reproduce in-process; the overlap half is provably
out of unit scope, by construction, not by omission.

### 4.3 Status

Root 1 is **mitigated out-of-band**: single-instance guard enabled (`d6d8b05`) + `RuntimeDirectory=eclipse-obd`
(`fae7ee7`) + Pi deploy. US-389 bakes the guard + RuntimeDirectory into the deploy path as a tested
matched-pair invariant and confirms the 06-06 spawn trigger; US-390 confirms the server-side
`detect_overlapping_drives` tripwire still stamps `data_quality=attribution_anomaly` as the backstop.

---

## 5. Spool's connection_log finding (incorporated)

Spool's 2-table corroboration (`connection_log` + `realtime_data`) is consistent with — and was the
first independent evidence for — the split above:

- **`drive_start = 29`, `drive_end = 18`** → 11 unclosed drives = the Root-2 missed-close signature.
  A drive that absorbs the next one shows as a `drive_start` with no matching `drive_end` for the
  absorbed leg.
- **Zero `drive_id` on any connection failure / disconnect** → comms-drop is **ruled out** as the
  cause. The K-line is stable mid-drive; the drive is not closing because the *close signal never
  fires*, not because the link died and orphaned an id. (A dropped link would not even carry a
  `drive_id`.) This directly supports modelling the missed close as the **absence of ticks**, which
  is exactly what the US-386 reproducer does (RPM-only, no comms events).

---

## 6. One-root hypothesis: **REFUTED** — two independent roots

The story's opening hypothesis was that both observed defects — *(1) drive fails to close* and
*(2) a second drive_id opens over an open one (ids out of temporal order)* — **share a single root**
(an unreliable close signal). The evidence refutes this:

| Observed defect | Root | Mechanism | Reproducible in-process? |
|---|---|---|---|
| (1) drive fails to close; later key-on absorbed into stale id | **Root 2** | tick-driven close never evaluated after readings stop; resume continues the stale session | **Yes** (US-386 RED) |
| (2) two drive_ids open at once, out of temporal order | **Root 1** | two concurrent processes racing the shared `drive_counter`; per-process drive context | **No** (needs 2 processes) |

They are **distinct**: Root 2 is a *single-process state-machine* bug (the close path is unreachable
when ticks stop) and produces **absorption** (one id spanning two drives — *fewer* ids than drives).
Root 1 is a *deploy/process-singleton* bug and produces **overlap** (two ids open at once — *more*,
out-of-order ids). A fix to one does not address the other. The earlier "unreliable close signal"
framing conflated the two because both surface in the same `connection_log` as
`start_count ≠ end_count`, but the mechanisms, the fixes, and the reproducibility differ.

> Note on terminology: Root 2 absorption *reduces* the distinct-id count for a window; Root 1 overlap
> *increases* it. The live 29/18 figure is dominated by Root 2 (missed closes). The out-of-temporal-order
> overlap rows are the Root 1 signature.

---

## 7. What US-388 must fix (hand-off scope, no fix here)

Per Atlas's ruling the Root-2 target behaviors are (US-388 will render the exact change shape):

1. **Guaranteed close** — the open drive must close even when ticks stop. The tick-driven-only design
   is the root: a close decision that can only be evaluated by a reading that never arrives is
   structurally unreliable. (Candidate directions for US-388/Atlas: an idle/connection-lost-driven
   close, or a time-anchored re-evaluation — *design decision, out of scope here*.)
2. **Mint `drive_id` only when actually entering `RUNNING`** — a resume after a missed close must
   reach `_startDrive` and mint a fresh id, not silently continue a stale session.
3. **Gap-fence the drive_id latch** — idle/KOEO rows must carry `NULL drive_id` so a stale-open
   cannot absorb a later key-on.

The US-386 reproducer is the acceptance oracle: US-388 makes
`test_backToBackMissedClose_*` and `test_keyOnAfterMissedClose_*` GREEN and removes their `xfail`
markers; US-390 locks the file into the regression manifest.

---

## 8. Evidence index

| Claim | Evidence |
|---|---|
| Close is tick-driven only | `processValue` (`detector.py:521`) is sole evaluator; called only at `event_router.py:404-407` |
| Connection-lost does not close | `_handleConnectionLost` (`event_router.py:522-556`) never calls the detector |
| RPM-debounce needs a post-60s tick | `detector.py:665-672` |
| ECU-silence needs a heartbeat tick | `_checkEcuSilenceDriveEnd` (`detector.py:932-986`), called at `detector.py:569` |
| Resume sets `_lastEcuReadingTime` before silence check | `detector.py:545-546` then `:569` |
| Resume continues, no new id | `_processRpmValue` RUNNING/STOPPING branches (`detector.py:655-677`); `_startDrive`/`_openDriveId` not reached |
| Concurrency hazard in id mint | `nextDriveId` no `BEGIN IMMEDIATE` (`drive_id.py:211-231`); per-process singleton (`drive_id.py:265-266`) |
| Single detector can't overlap | one `_currentSession` (`detector.py:218`); only `_endDrive` exits RUNNING (`detector.py:790`) |
| RED reproduced | `pytest ... --runxfail` → both stale-open scenarios `got=[1]`; control + determinism PASS |
| Spool corroboration | `drive_start=29 / drive_end=18`; zero `drive_id` on comms failure |
