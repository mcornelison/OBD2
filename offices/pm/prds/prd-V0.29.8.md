---
sprint: 54
version: V0.29.8
status: draft
createdAt: 2026-07-03
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-OPS, E-002, E-004
feature: F-117, F-062, F-082, F-051, F-054, F-049
theme: OBD capture reliability (P0) + data-integrity + power hygiene
validationMode: BENCH ONLY for the code + a live sustained-capture DRIVE for F-117 (thread-named instrumentation; the mocked-connection tests are green while the live path captures nothing) -- the F-117 acceptance drill needs the car
selectedStories: [US-441, US-442, US-443, US-444, US-445, US-432, US-447]
---

# PRD: Sprint 54 / V0.29.8 — OBD capture reliability (P0) + data-integrity + power hygiene

| Field | Value |
|---|---|
| Sprint | 54 |
| Version | V0.29.8 (patch on the V0.29 chain) |
| Branch | `sprint/sprint54-V0.29.8` (forks from `dev`) |
| Validation | **BENCH** for the code; **F-117 needs a live sustained-capture drive** (car) to prove capture works — its unit tests can't (they mock the connection). |
| Story range | US-441 … US-447 (7 stories) |

## 1. Introduction / Overview

**P0: the Pi captures 0 OBD rows** (Atlas's CIO-directed live-car RCA — `offices/architect/findings/2026-07-03-obd-capture-rca-eclipse-obd-connection-thread-race.md`). Hardware/pairing/ECU are all cleared; the bug is a **connection-thread race** in eclipse-obd. The crash-loop hotfix (`f389d5b`) is deployed (Pi stable) but is NOT the capture fix. **US-441 fixes capture** and leads the sprint.

The rest is bench-verifiable data-integrity + power hygiene so Ralph has a full plate while the F-117 car-drill happens separately.

## 2. Goals

- **Restore OBD capture** — serialize the connection, fence orphaned timeout daemons, preserve the no-boot-hang property; prove it with a live drive.
- Clean up the historical orphan `drain_event` rows (US-434 finding).
- Land the tester's V0.28+ data-profile **design** improvements (the bugs shipped in US-437).
- Close power-reliability gaps: slow-drain detection, battery-test-on-boot, drive_statistics writer.
- Zero drive drills for the non-F-117 code.

## 3. User Stories

> **US-441 is P0 and gates real capture.** Everything else is bench-verifiable — Ralph builds regardless of the car. **US-432 deps US-441** (the two capture fixes; validated together in one A-9 car re-gate).
>
> **All code stories: `ruff` + `mypy` (strict) clean** (Atlas GAP-2; CLAUDE.md standard).
>
> **Post-review changes:** US-432/BL-016 is **now IN** (Atlas ruled Option B — a real distinct defect, not a race artifact). US-446 (drive_statistics) is **DEFERRED to Sprint 55** — it's derived analytics in Atlas's F-104 lane; building it Pi-side now risks the churn F-104 exists to prevent.

---

### US-441: OBD capture — serialize connection + fence orphaned timeout daemons (F-117, P0)
**Description:** As the CIO, I want eclipse-obd to actually capture OBD rows on the car, so the entire data pipeline works again.

> **Build to Atlas's RCA.** Root cause: python-obd's connection is NOT thread-safe; orphaned timeout-daemon threads (TD-036/US-244 anti-boot-hang) + the US-301 heartbeat path touch the shared `self._connection.obd` concurrently with the logger → serial I/O interleaves → empty read → 0 rows every connect. Standalone (1 thread) works. (`lifecycle.py:760-885, 921-965`.)

**Acceptance Criteria:**
- [ ] **The single serialization lock lives on the `ObdConnection` WRAPPER (`obd_connection.py`), NOT `lifecycle.py`** (Atlas GAP-1, load-bearing) — it guards EVERY `.obd` access (connect / query / close / probe). **ALL callers acquire that one lock:** the lifecycle connect/query daemons, the US-301 heartbeat path, **AND the realtime logger's direct reads at `logger.py:220 AND 290`** (which do NOT route through lifecycle). A lifecycle-only lock leaves the logger↔daemon race alive while a mocked-at-lifecycle test passes green — the exact mocked-green/IRL-miss trap.
- [ ] **Fence orphaned timeout daemons** — a timed-out connect/query thread is BARRED (ownership/generation token) from touching a connection a later thread owns; it cannot corrupt serial I/O for the owner.
- [ ] **Preserve the TD-036 no-boot-hang property** — the anti-boot-hang timeout behavior must not regress (bounded connect; boot never hangs).
- [ ] **Thread-named instrumentation** so the concurrency is observable in logs (which thread touched the connection when).
- [ ] **Real-concurrency test (Atlas GAP-1 VC):** spin the LOGGER read path concurrently with a superseded/orphaned daemon against the SAME wrapper instance + assert no interleaving — exercises the cross-layer race, not just lifecycle-internal threads. Fails pre-fix, passes after.
- [ ] **Rule-10 bound to THIS story (Atlas GAP-3, A-11):** US-441 does NOT close until the connection-threading-model section of `specs/architecture.md` is updated in-sprint (authored here or in US-447, but gated on US-441).
- [ ] **Acceptance drill (car):** a live sustained-capture drive shows `realtime_data` rows accumulating steadily (not 0, not first-read-then-disconnect) — the F-117 acceptance (CIO's car; the one A-9 re-gate also exercises US-432).
- [ ] `ruff check` **+ `mypy` (strict)** pass (Atlas GAP-2).

**Downstream impact:** The `ObdConnection` wrapper + all its callers (`lifecycle.py`, `logger.py:220/290`, US-301 heartbeat); the P0 gate for all capture-dependent validation + `/chain-validated`. Atlas calls this **A-17**.

---

### US-442: Clean up historical orphan `drain_event` rows (from US-434)
**Description:** As the CIO, I want the historical open `drain_event` rows closed/annotated, so the drain history is honest.

**Acceptance Criteria:**
- [ ] The 4 historical orphan `drain_event` rows flagged in US-434 are closed/annotated with provenance (documented as historical, not silently deleted).
- [ ] A guard/note so the (now-moot) drain_event path doesn't re-orphan.
- [ ] DB-verified; `ruff check` passes on any `.py`.

**Downstream impact:** `drain_event` table hygiene (server + Pi).

---

### US-443: Tester V0.28+ data-profile — DESIGN improvements (F-082, the 8 design items)
**Description:** As the CIO, I want the tester's data-profile **design** recommendations implemented (the bugs shipped in US-437), so the dataset quality improves.

**Acceptance Criteria:**
- [ ] Read the tester's V0.28+ data-profile findings; enumerate the **8 design items** (distinct from the US-437 bugs).
- [ ] Implement the ready ones OR file/defer with rationale (some may need Spool/Atlas input — flag those, don't guess).
- [ ] Each implemented item has a test / DB-verification; `ruff check` passes.

**Downstream impact:** Data-quality/schema improvements per the tester's recs.

---

### US-444: UpsMonitor slow-drain detection + flap-debounce (F-051)
**Description:** As the system, I want slow-drain detected + flap-debounced, so gradual battery drain is caught without false alarms.

**Acceptance Criteria:**
- [ ] Slow-drain detection (sustained gradual VCELL decline over a window) with flap-debounce (no rapid on/off).
- [ ] Bench-verifiable on the UPS-drain rig; unit test for the debounce.
- [ ] `ruff check` passes.

**Downstream impact:** UpsMonitor; pairs with the Sprint-53 SOC% calibration.

---

### US-445: Automated battery test on boot (F-054)
**Description:** As the system, I want a battery health check on boot, so degradation is surfaced early.

**Acceptance Criteria:**
- [ ] A boot-time battery test (register read + a health assessment) that logs a result to `battery_health_log` / state.
- [ ] Honest-instrument: undeterminable → unknown (no confident wrong health).
- [ ] Bench-verifiable; `ruff check` passes.

**Downstream impact:** Boot path + `battery_health_log`.

---

### US-432: idle-poll cold-boot RPM-mask fix (BL-016, Option B; the 2nd capture fix; deps US-441)
**Description:** As the system, I want RPM readable after a cold-boot-key-OFF connect so a drive actually starts, so idle-poll doesn't miss engine-on even once F-117 restores capture.

> **Atlas-RULED Option B** (`offices/architect/reports/2026-07-03-bl016-us432-idle-poll-rpm-mask-fix-ruling.md`). A **real, distinct defect** confirmed in code (independent of the A-17 race): a `supported_commands` set built while the ECU is dark marks RPM UNKNOWN (not unsupported) → every RPM query returns null-without-wire-traffic → escalation swallows it → `drive_start` never fires. **Deps US-441** (the race must be fixed first; both validate in one A-9 car re-gate — A-17 fix does NOT fix the mask, mask fix does NOT fix the race).

**Acceptance Criteria:**
- [ ] Un-mask RPM past python-obd's dark-ECU support cache via a **`force`** read, **scoped to known-mandatory Mode-01 PIDs (RPM minimum)** — NEVER blanket (blanket re-exposes the 0x42/0x0B/0x15 garbage US-199 skips). RPM is mandatory Mode-01 = known-supported → forcing corrects a false-negative, not a genuinely-unsupported PID.
- [ ] Applied to **BOTH the escalation probe AND the ongoing poll** — implement as a connection-scoped "engine-confirmed → force mandatory PIDs" latch, set on the escalation edge (`core.py:1205`), cleared on drive_end (`1264`) + disconnect. (Decisive: `drive_start` fires only on RPM sustained > threshold across ticks at `detector.py:660-667` — one probe isn't enough; the ONGOING poll must un-mask.)
- [ ] **US-388 non-regression:** touches ONLY the read path (force flag) — does NOT touch `evaluateTimeouts` / `_maybeCloseOnDeadline` / `_openDriveId` / the NULL-latch / `_startDrive`. drive_start fires through the unchanged RPM-sustained machine.
- [ ] **Live-Pi bench confirm** (folds into the A-9 re-gate): after engine-on in the cold-boot-key-OFF sequence, one forced `010C` returns real RPM + a drive_start row + non-NULL RPM.
- [ ] `ruff check` **+ `mypy` (strict)** pass.

**Downstream impact:** OBD read path (A-9 start-side); the 2nd capture defect. Re-groomed from the Sprint-53 block.

---

### US-447: Sprint 54 documentation sync (Rule-10)
**Description:** As the PM, I need docs current after the capture-reliability + power changes.

**Acceptance Criteria:**
- [ ] `specs/architecture.md` updated for the connection-serialization/threading model (F-117) + any power-path changes.
- [ ] `regression_manifest.json` reflects the sprint's features (esp. F-117 capture).
- [ ] No stale references.

**Downstream impact:** Docs only.

## 4. Non-Goals (Out of Scope)

- **US-446 / F-075 (drive_statistics Pi-side writer)** — DEFERRED to Sprint 55 under the F-104 gate (Atlas: derived analytics in his server-authority lane; Pi-side-now risks F-104 churn). If it ever ships Pi-side it must be bounded advisory/local-only, server retains re-derive authority (A-4).
- **F-104 (Server-Side Analytics Authority)** — Atlas design gate still owed → Sprint 55.
- **F-083 (Mahalanobis)** — needs a clean baseline (which needs F-117 capture working first) → Sprint 55.
- **`/chain-validated`** — doubly-gated: F-117 capture + Bug-3a display, both need the car.

## 5. Open Questions

1. **(F-117 sizing)** US-441 is the whole capture fix + instrumentation + a real-concurrency test — likely **L** (pmSignOff at freeze); split the instrumentation/test-harness from the lock/fencing if it runs heavy?
2. **(US-446)** Pi-side vs server-side for drive_statistics — confirm with Spool's Approach-2 note + B-104.
3. **(US-443)** the 8 design items — which are Ralph-buildable vs need Spool/Atlas input.

## Action Items (NOT sprint stories)

- **AI (car/CIO):** the F-117 acceptance is a **live sustained-capture drive** — the drill that finally proves on-Pi capture (and unblocks the capture side of `/chain-validated`). Pairs with the Bug-3a display drill.
