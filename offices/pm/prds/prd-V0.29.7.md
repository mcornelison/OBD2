---
sprint: 53
version: V0.29.7
status: draft
createdAt: 2026-07-02
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-OPS, E-002, E-003, E-004
feature: F-048, F-049, F-050, F-062, F-102, F-106, F-082, F-069, F-004
theme: Analytics foundation + ops/power hygiene
validationMode: BENCH ONLY (unit/fixture + DB introspection + live-Pi re-query for verify-first items + UPS-drain rig -- NO drive drills; some items are analysis/CLI, bench-verifiable)
selectedStories: [US-431, US-432, US-433, US-434, US-435, US-436, US-437, US-438, US-439, US-440]
---

# PRD: Sprint 53 / V0.29.7 — Analytics foundation + ops/power hygiene

| Field | Value |
|---|---|
| Sprint | 53 |
| Version | V0.29.7 (patch on the V0.29 chain) |
| Branch | `sprint/sprint53-V0.29.7` (forks from `dev`) |
| Validation | **BENCH ONLY** — unit/fixture, DB introspection, live-Pi re-query (verify-first), UPS-drain rig. No drive drills. |
| Story range | US-431 … US-440 (10 stories) |

## 1. Introduction / Overview

Two threads the CIO prioritized: **(A) analytics/data-integrity foundation** — derived signals, the tester's data-profile bug backlog, a cross-drive comparison tool; and **(B) ops/power hygiene** — the SOC% calibration follow-on to Sprint 52's `_soc_pct`, several power/drain-path fixes, hostname cleanup, and dependency hygiene.

**Deferred (with reasons):** F-104 (Server-Side Analytics Authority) is architectural → routed to Atlas for a design gate, groomed into **Sprint 54**. F-083 (Mahalanobis baseline) needs a clean baseline dataset → pairs with F-104 in Sprint 54.

## 2. Goals

- Calibrate + trust the MAX17048 SOC% now that `_soc_pct` has a home (Sprint 52).
- Close the power/drain-path gaps (idle-poll detection, DB-write activation, drain_event close).
- Add derived signals (acceleration, estimated distance) server-side.
- Clear the tester's V0.28+ data-profile **bugs** (defer the design items).
- Give Spool a cross-drive comparison tool.
- Retire hostname/dependency debt + archive stale backlog items.
- Zero drive drills.

## 3. User Stories

> **Placement note for Atlas's review:** derived signals (US-436) + the cross-drive tool (US-438) should follow the **Pi-emitter / server-authority** pattern (B-104) — compute server-side, not on the Pi — unless you rule otherwise. Several items are **verify-first** (re-query the live Pi before changing code).

---

### US-431: MAX17048 SOC% calibration protocol + scripts (F-048)
**Description:** As the CIO, I want a repeatable SOC% calibration/learning run for the MAX17048, so the `_soc_pct` values recorded (Sprint 52) are trustworthy despite the cold-start mis-read.

**Acceptance Criteria:**
- [ ] A documented calibration protocol + script (`offices/tuner/scripts/` or `scripts/`) that runs a controlled charge/discharge learning cycle and captures the register's SOC% vs a known reference.
- [ ] Output feeds the US-234/US-427 cold-start guard threshold (the ~3-min window) with real data, not a guessed constant.
- [ ] Bench-verifiable on the UPS-drain rig; results documented.
- [ ] `ruff check` passes on any `.py`.

**Downstream impact:** Informs the `_soc_pct` cold-start guard; no schema change.

---

### US-432: drive_detect idle-poll gap — engine-on never detected in idle-poll mode (F-049, verify-first + A-9 guardrails)
**Description:** As the system, I want engine-on reliably detected in the idle-poll path, so a drive isn't missed when the poll loop is in its idle cadence.

> **Atlas-reviewed:** VERIFY-FIRST — US-242/B-049 **already built** idle-poll→active-poll escalation on engine-on (alternator `BATTERY_V` + RPM-probe injection, `core.py:356/1200/1212`). Root-cause the **RESIDUAL** gap, do NOT re-solve. **A-9 design-gate DoD** (Atlas's lane — start-side, distinct from A-9's close roots).

**Acceptance Criteria:**
- [ ] **Verify-first:** confirm the residual gap on the live Pi against the existing US-242/B-049 escalation; state the specific mechanism that still misses.
- [ ] Fix the residual gap so an engine-on transition promotes the poll cadence + fires drive_start within the expected window.
- [ ] **A-9 guardrail (a):** must NOT regress US-388's close-guarantee (`evaluateTimeouts`/deadline-anchored) or the `drive_id` NULL-latch.
- [ ] **A-9 guardrail (b):** fold this into the A-9 IRL re-gate (missed-start-in-idle-poll = another drive-lifecycle failure to exercise).
- [ ] Unit test simulating idle→engine-on; `ruff check` passes.

**Downstream impact:** DriveDetector start-side (A-9 lane; Atlas design-gate DoD).

---

### US-433: PowerMonitor DB-write path activation — UpsMonitor → power_log (F-050, verify-first)
**Description:** As the system, I want the UpsMonitor readings written to `power_log`, so power history is captured.

> **Atlas-reviewed: almost certainly DONE** — `lifecycle.py:1873` "PowerMonitor initialized (US-243 power_log write path active)" + synced via US-412. Expect **close-with-evidence**, not new code.

**Acceptance Criteria:**
- [ ] **Verify-first:** re-query the live Pi — confirm `power_log` is populating (US-243 path + US-412 sync). If live + healthy, **close with evidence** (row counts + recent timestamps).
- [ ] Only if a real gap remains: activate/repair the UpsMonitor → `power_log` write path (VCELL/SOC/CRATE/power_source per poll).
- [ ] Bench-verifiable; `ruff check` passes on any `.py`.

**Downstream impact:** Feeds `power_log` (now server-synced per US-412).

---

### US-434: drain_event close-on-poweroff targeted fix (F-062)
**Description:** As the system, I want drain_event rows to close cleanly on poweroff, so drain records aren't left open.

> **Atlas-reviewed: very likely MOOT** — `startDrainEvent`/`endDrainEvent` have **0 production callers** (`hardware_manager.py:73`; only the CLI drill + tests, which open+close in one run). Nothing opens a drain_event during operation → nothing left open at poweroff. Expect **no-op / close-with-evidence**. A real open-path would be a NEW feature contradicting the retired ladder + the BL-015 "~10s shutdown ≠ real drain" semantic — do NOT build it here.

**Acceptance Criteria:**
- [ ] **Verify-first:** confirm 0 production `startDrainEvent` callers + no stuck-open `drain_event` rows post-poweroff → **close as moot with evidence** (no code).
- [ ] Only if a real open-path is found (unexpected): a targeted close in `ShutdownSequencer` (`power_watch/controller.py`) — but flag to PM/Atlas first (it contradicts the retired ladder).
- [ ] `ruff check` passes on any `.py`.

**Downstream impact:** Expected no-op; honestly closes F-062.

---

### US-435: Pi + server hostname resolution cleanup (F-102)
**Description:** As the CIO, I want hostname references consistent, so tooling resolves the Pi correctly (it now reports `Chi-Eclips-01`).

**Acceptance Criteria:**
- [ ] Sweep code/config/docs/SSH-config for stale hostname references (`chi-eclipse-tuner`, old aliases) → the canonical current name; deploy/SSH paths resolve.
- [ ] No functional regression in deploy-pi.sh / SSH access.
- [ ] `ruff check` passes on any `.py`.

**Downstream impact:** Deploy + SSH tooling; doc references.

---

### US-436: Derived signals — acceleration + estimated distance from speed+time (F-106)
**Description:** As the CIO, I want acceleration + estimated distance derived from the existing speed+time stream, so drives have richer motion context without new PIDs.

**Acceptance Criteria:**
- [ ] Compute acceleration (Δspeed/Δtime) + estimated distance (∫speed·dt) **server-side** (Pi-emitter/server-authority per B-104 — confirm placement with Atlas).
- [ ] Derived values stored/queryable per drive; guard against divide-by-zero / gaps.
- [ ] Unit tests against canned speed/time series; `ruff check` passes.

**Downstream impact:** New derived columns/computation server-side; no new Pi PIDs.

---

### US-437: Tester V0.28+ data-profile findings — BUG rollup (F-082, scoped)
**Description:** As the CIO, I want the tester's confirmed data-quality **bugs** fixed, so the dataset is trustworthy.

**Acceptance Criteria:**
- [ ] Read the tester's V0.28+ data-profile findings (`offices/tester/findings/` or the rolled-up feature file); enumerate the **8 bugs** (the 8 design items are OUT — deferred).
- [ ] Fix each confirmed bug OR mark it already-resolved-with-evidence (some may have been fixed since filing).
- [ ] Each fix has a test / DB-verification; `ruff check` passes.

> Scoped to the bugs only; the 8 design items are a separate future story.

**Downstream impact:** Data-quality fixes across the pipeline; verify per bug.

---

### US-438: Cross-drive comparison tool (F-069, Spool ergonomics)
**Description:** As Spool, I want a tool to compare metrics across drives, so tuning analysis is faster.

**Acceptance Criteria:**
- [ ] A CLI/query tool that compares chosen metrics across N drives (e.g., peak RPM, knock-retard, LTFT, the US-436 derived signals) side-by-side.
- [ ] Server-side (reads `obd2db`); honest about missing/foreign data (excludes `data_source!='real'` per F-116).
- [ ] Bench-verifiable against existing drives; `ruff check` passes.

**Downstream impact:** New analysis tool (`offices/tuner/scripts/` or `src/server/`); read-only.

---

### US-439: Evaluate + fix commented dependencies (F-004)
**Description:** As the maintainer, I want the commented-out dependencies evaluated + resolved, so `requirements` is honest.

**Acceptance Criteria:**
- [ ] Audit commented deps in `requirements*.txt` / `pyproject.toml`; for each: restore-and-use, remove-as-dead, or document-why-commented.
- [ ] No import breakage; `ruff check` + a targeted import smoke pass.

**Downstream impact:** Dependency hygiene.

---

### US-440: Sprint 53 documentation sync + backlog archival (Rule-10)
**Description:** As the PM, I need docs current + the stale backlog archived.

**Acceptance Criteria:**
- [ ] `specs/architecture.md` updated for derived signals + any power-path changes.
- [ ] `regression_manifest.json` reflects the sprint's features.
- [ ] **Backlog archival:** archive the verified-stale/superseded — **F-007, F-052, F-100** + **US-422, US-423** (superseded by Sprint 52) — status → superseded/declined + moved to archive.
- [ ] No stale references.

**Downstream impact:** Docs + backlog hygiene.

## 4. Non-Goals (Out of Scope)

- **F-104 (Server-Side Analytics Authority)** — architectural; routed to Atlas for a design gate → Sprint 54.
- **F-083 (Mahalanobis baseline)** — needs a clean baseline dataset → Sprint 54 (with F-104).
- **The 8 F-082 design items** — after the bugs; separate future story.
- **`/chain-validated`** — the whole V0.29 chain still awaits bench validation + the Bug-3a live car drill.
- **No drive drills.**

## 5. Open Questions — RESOLVED by Atlas's review (2026-07-02)

1. ✅ **Placement:** US-436 + US-438 **CONFIRMED server-side** (B-104: server is sole analytics writer).
2. ✅ **US-432:** Ralph-ownable WITH the A-9 design-gate DoD (2 guardrails, folded into the story above) + verify-first (US-242/B-049 already built the escalation).
3. ✅ **US-434:** very likely MOOT (0 production callers) — verify-first → close-with-evidence.
4. ✅ **Verify-first:** US-433 almost certainly DONE (US-243 + US-412); US-434 moot; US-437 per-bug verify (can't pre-judge).

**Sizing flag (Atlas → `/resize-sprint`):** US-433 + US-434 are likely no-ops → effectively ~8 real stories. Decide at resize whether to accept 8-effective or pull one deferred item forward.

## Action Items (NOT sprint stories)

- **Route Atlas for F-104 (Server-Side Analytics Authority) design gate** — for Sprint 54 grooming.
