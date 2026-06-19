# Atlas Architecture RCA + Ruling — A-9 DriveDetector defect (drives 28/29 recurrence)

**By:** Atlas (Architect) · **Date:** 2026-06-19 · **Tasked by:** CIO
**Severity:** HIGH (data-attribution corruption) · **Verdict: root cause IS architectural; ruling below**
**Evidence base:** finding `findings/2026-06-18-drivedetector-defect-recurs-28-29.md`; Spool inbox ×2 (2026-06-18); the May drives-23/24 finding; and direct reads of `src/pi/obdii/drive/detector.py`, `drive_id.py`, `orchestrator/lifecycle.py`, `orchestrator/single_instance.py`, `src/server/analytics/overlap.py`, `config.json`, git.
**Companion:** refines the A-9 RCA sprint already routed to PM (US-386..389, draft/unfrozen).

---

## 0. Bottom line (one screen)

A-9 has **two distinct architectural roots**, not one:

| | Root 1 — concurrent-emitter dual-attribution | Root 2 — stale-open-drive leak (unreliable close) |
|---|---|---|
| Symptom | overlapping drive_ids, id minted out of temporal order (28 inside 29; 29 started first, higher id) | drive never closes; a later key-on inherits the stale id (29 absorbed an 8-day-later key-on); connection_log: 29 starts, **18** ends |
| Mechanism | **two concurrent orchestrator processes**, each its own DriveDetector + process-global `_currentDriveId` + DB connection, both minting from the one `drive_counter` | the close signal is **contingent on events that don't reliably arrive**; the process-global `_currentDriveId` latch stays set, so idle/KOEO rows inherit a stale id |
| F-107 status | **FIXED, but shipped `default-OFF`** (Mechanism B single-instance guard) — **never enabled in prod** | **NOT addressed at all** |
| My ruling | **Rule-10 SIGN-OFF to enable the guard** (conditions §3.1). Highest-leverage; already built. | **New RCA + fix required** — enforce a guaranteed close + stamp-only-when-active + gap-fence (§3.2). |

Plus a **strategic fork I own** (§4): the server is currently a *detector/flagger*, not a *re-segmenter*. Long-term, drive-boundary **segmentation authority should move server-side** (B-104-aligned), demoting the Pi `drive_id` to an advisory hint — so a future Pi regression is *recovered*, not just flagged. Sequence the Pi fixes first; the server re-segmenter is a separate epic.

This is **not a chain/deploy block** — the V0.28.0 server tripwire caught both drives and the raw data is intact (defense-in-depth vindicated). It is a HIGH-priority Pi-side correctness fix.

---

## 1. Is it architectural? Yes — and the evidence says exactly why

### 1.1 Minting + the drive-lifecycle state machine (verified in code)
- **ID mint** = a single-row `drive_counter` table, `nextDriveId()` does `UPDATE … +1` then `SELECT` (`drive_id.py:211-231`). Monotonic **by counter order, not wall-clock**. The docstring itself warns it is only safe "on a single connection… for multi-connection setups the caller should wrap in BEGIN IMMEDIATE."
- **The current-drive id is a process-global latch** (`_currentDriveId`, module-level in `drive_id.py:265`), set on `_startDrive` and cleared on `_endDrive`. Writers stamp every row with `getCurrentDriveId()` at write time.
- **The state machine self-guards a single thread.** `_startDrive` is reachable only from the `STARTING` branch (`detector.py:648`); after it runs `_transitionState(RUNNING)` (748) further ticks route elsewhere. **So a double-mint/overlap is impossible within one thread** — it *requires concurrency* (two threads/processes, each with its own latch + connection).

### 1.2 Root 1 — already RCA'd, already fixed, shipped disabled
The `single_instance.py` header states it outright, and it matches my independent code reasoning:
> "F-107 Mechanism B from the US-360 RCA: **the Drive 23/24 production dual-attribution was two concurrent emitter processes**, each with its own DriveDetector + process-global drive_id, both minting from the shared drive_counter and time-overlapping one physical leg."

The fix (a pidfile guard with a liveness probe that refuses a second live starter) is correct. **But it is gated `default-OFF`** (`lifecycle.py:544` — `if not guardConfig.get('enabled', False): return`), explicitly "pending Atlas Rule 10 sign-off + CIO review" (`lifecycle.py:528-535`), and **`config.json` has no `pi.runtime.singleInstanceGuard` block** (verified) → the guard is **OFF in production.** Drives 28/29 occurred 06-06, *after* the 06-01 V0.28.0 deploy — i.e. with the fix present but disabled. **That is why the dual-attribution recurred.**

What F-107 *did* enable for this root is **Mechanism A** (`detector.py:719-736`): re-attach to the prior id when an ECU-silence tentative end is followed by an engine resume within `MIN_INTER_DRIVE_SECONDS`. That covers the **single-process mid-drive-dropout** case only — not two processes. So the production root was left unguarded.

### 1.3 Root 2 — the close path is not guaranteed (untouched by F-107)
Every close path and its reliability (verified in `detector.py`):
| Path | Fires when | Reliability |
|---|---|---|
| RPM-debounce (`STOPPING`→end, :672) | RPM ≤ end-threshold for 60 s continuous | fails if the ECU goes silent *before* RPM reaches 0 (typical at key-off) |
| ECU-silence tentative end (:932-986) | no ECU PID for 60 s | gateable (`driveEndDurationSeconds<=0` disables, :962); needs the poll loop alive; tentative |
| `forceKeyOff()` (:1244) | **only** the power-down IMMINENT stage calls it (sole caller = `lifecycle.py`) | not wired to connection-loss |
| `detector.stop()` (:466) | clean app shutdown | lost on crash / SIGKILL / power-cut |

**Connection-loss does NOT close a drive** (`event_router._handleConnectionLost` does not call `forceKeyOff`/close — verified: `forceKeyOff` has exactly one caller, the power-down path). When no close path fires, the `_currentDriveId` latch stays set, and **any later rows — even an idle/KOEO event days later — inherit the stale id** because writers stamp `getCurrentDriveId()` regardless of drive state. That is precisely drive 29 absorbing the 06-14 key-on, and the `connection_log` ledger (29 starts / 18 ends → **11 drives never closed**) is the smoking gun that this is systemic, not a one-off. This is the **F-7 "drive-end never fires" bug class, now living inside the DriveDetector itself.**

### 1.4 The unification I missed in May
In the May drives-23/24 finding I classified the defect as "drive-*start* fires twice" and explicitly said it was **not** the older "drive-*end* never fires" family. The June evidence corrects that: the close path **does** fail (11/29 unclosed). The honest architectural picture is **two roots that compound** — an unreliable close (Root 2) leaves a drive open, and the absence of a single-instance/single-open guarantee (Root 1) lets a second emitter mint a parallel id. F-107 patched a narrow path of one root and disabled the real fix for the other.

---

## 2. Violated invariants (the architectural defect, stated precisely)

The DriveDetector lacks enforcement of three lifecycle invariants:

1. **Single emitter / single open drive per machine.** At most one process may mint+stamp drive_ids at a time. *(Root 1 — the single-instance guard enforces this; it's built but off.)*
2. **Every opened drive deterministically closes (or is fenced).** Close must not depend on a future signal that may never arrive. *(Root 2 — unaddressed.)*
3. **A row carries a drive_id only if it belongs to an active, open drive.** The `_currentDriveId` latch must never outlive the drive it names. *(Root 2 corollary — unaddressed.)*

These are design-level guarantees, not line bugs. The root **is architectural.**

---

## 3. Ruling — fix design (invariants + options; engineering is Ralph's)

### 3.1 Root 1 — RULE-10 SIGN-OFF: enable the single-instance guard ✅ (with conditions)
The guard (`single_instance.py`) is the correct structural fix and is the highest-leverage action — it's already built and tested. **I sign off Rule 10 to enable it**, conditions:

- **C-1 (deploy-hygiene, the trade-off the spec flagged):** the guard refuses a *second live* starter, so the deploy/restart path MUST `systemctl stop` (clean release) before start — otherwise a deploy that double-starts will have the new process correctly *refused* until the old exits. This pairs with **US-354** (the deploy-didn't-restart-cleanly class). Enable the guard **and** fix deploy hygiene; they're complementary. *(Fail-safe note: if mis-deployed, the failure is "new code waits for old to stop," not "two drives" — the honest-instrument-preferred failure.)*
- **C-2 (stale-lock safety):** lockPath defaults to `/run/eclipse-obd/orchestrator.lock` on tmpfs (cleared on reboot) and the guard reclaims dead-pid locks via a non-destructive liveness probe (Windows-safe — no `os.kill(pid,0)` kill). Confirmed adequate; keep lockPath on `/run`.
- **C-3 (RCA must still name the spawn source):** the guard refuses the second process regardless of *why* two spawned, but the RCA should confirm from the Pi journal that two `eclipse-obd` PIDs existed around 06-06 02:25 and identify the spawn trigger (systemd `Restart=` race? watchdog? manual+service overlap?) so we know the guard fully covers it. This is the one piece of Root 1 still needing empirical confirmation — I rule the mechanism with high confidence (overlap ⇒ concurrency; guard off), but verify-before-asserting requires the journal proof.
- **C-4 (design-gate DoD):** enabling is a load-bearing boot-path change → lands with a `specs/architecture.md` update in-sprint.

### 3.2 Root 2 — NEW RCA + fix required (close-guarantee). Invariant > mechanism.
Enforce invariants #2 and #3. Design options (Ralph/RCA choose; I rule the invariant + recommend the pair):
- **(a) Reliable close:** wire a drive-close into `_handleConnectionLost` (connection-loss ends/fences the drive), and make the inactivity close a true watchdog — a drive closes after N seconds with no RPM-bearing ECU data, independent of adapter heartbeat and not disable-able for the *latch-clearing* purpose.
- **(b) Stamp-only-when-active (recommended):** writers stamp a drive_id **only when `state == RUNNING`**; idle/KOEO/parked rows get `NULL` (the schema's correct "no active drive" sentinel — already supported). This structurally prevents stale-id inheritance even if a close is missed.
- **(c) Gap-fence the latch (recommended):** the current-drive context auto-expires on any inter-row gap > threshold, so an 8-day (or any large) gap can never inherit a prior id.
- **Recommendation:** (b)+(c) as defense-in-depth (stamp gated on active state *and* a gap fence), plus (a) for cleanliness. (b)+(c) make the corruption impossible-by-construction rather than contingent on a close firing.

### 3.3 Minting atomicity (latent; lower priority)
`nextDriveId`'s `UPDATE`+`SELECT` is non-atomic across connections. **Moot once the single-instance guard holds** (only one minter). Keep as a belt-and-suspenders note: if the architecture ever legitimately runs concurrent minters, wrap mint in `BEGIN IMMEDIATE` (the docstring already says so). Not required for this fix.

### 3.4 IRL gate hardening (why drive-27 falsely closed A-9)
Drive-27 was a single, normal-length, rested drive — too narrow; it never exercised the failure surface. The re-validation gate that re-closes A-9 **MUST** include:
1. a **short / back-to-back drive pair** (minutes apart, ~3-4 min each — the 28/29 shape);
2. a **key-on after a missed close** (prove a later key-on does not inherit a stale id);
3. a **deploy / double-start** attempt (prove the single-instance guard refuses the second process).

A single clean drive is **insufficient evidence** to close A-9 again. (This is also an A-11-family lesson: don't let a narrow gate stamp a broad guarantee.)

---

## 4. Strategic fork I own — Pi-authority vs server-authority for drive boundaries

The server overlap detector **groups by the Pi's `drive_id`** (`overlap.py:85-94`) and the 300 s-gap path likewise *flags*; neither **re-segments**. So today the server is a *detector/flagger* — honest (`data_quality='attribution_anomaly'`, raw never dropped) but **lossy**: it cannot recover 28/29, only exclude them. The Pi remains the de-facto **segmentation authority**, which sits awkwardly against the B-104 principle ("Pi = emitter, server = authority").

**Ruling:** do both, layered, sequenced:
- **Now (this RCA sprint):** fix the Pi roots (§3.1 enable guard, §3.2 close-guarantee). Cheap, mostly built, stops the corruption at source.
- **Strategic (separate epic, fold into the B-104 / EDR-bus line):** move **drive-boundary segmentation authority to the server** — a gap-based re-segmenter that treats Pi `drive_id` as *advisory* and re-derives boundaries from raw `realtime_data`, so a future Pi regression is **recovered, not just flagged**. Demote Pi `drive_id` to a hint; keep a Pi-local "current drive" notion **only** for live UI (the DELTA-2 live card), DTC drive_id stamping, and sync grouping — explicitly **not** the analytics authority. This is the same "server owns derived facts" SSOT principle as B-104 and the A-14 EDR-bus "SSOT-for-derived-data" direction — drive boundaries are a *derived fact* best owned where the full raw signal lives.
- **Not server-only now:** the Pi fix is cheaper and immediate; the re-segmenter is a real build best done in the B-104/EDR consolidation, with the tripwire holding the line meanwhile.

---

## 5. Disposition / routing
1. **A-9 stays OPEN (HIGH)** until the re-validation gate (§3.4) passes — *not* a single clean drive.
2. **Rule-10 sign-off recorded** to enable the single-instance guard (§3.1) — config flip + deploy is PM/Ralph/CIO (not my lane); I provide the architectural sign-off the spec was waiting on.
3. **A-9 RCA sprint (US-386..389) scope refined** by this ruling — see the PM note. The "RCA" story narrows to: confirm the spawn source in the journal (C-3) + reproduce both roots in-process; the fix stories implement §3.1/§3.2; US-fix stays build-blocked on the RCA confirmation (A-11 discipline).
4. **Server tripwire remains the backstop** — consumers exclude `attribution_anomaly` drives (28/29); the flag is trustworthy.
5. Routed: Spool (A2AL, he hit it), Marcus (PM brief), finding updated with a pointer, charter A-9 row updated.

— Atlas
