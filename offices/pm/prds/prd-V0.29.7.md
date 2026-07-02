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

### US-432: drive_detect idle-poll gap — engine-on never detected in idle-poll mode (F-049)
**Description:** As the system, I want engine-on reliably detected in the idle-poll path, so a drive isn't missed when the poll loop is in its idle cadence.

**Acceptance Criteria:**
- [ ] Root-cause the idle-poll gap (engine-on RPM not triggering drive_start when the loop is in idle/slow cadence); state the mechanism.
- [ ] Fix so an engine-on transition promotes the poll cadence + fires drive_start within the expected window.
- [ ] Unit test simulating idle→engine-on; `ruff check` passes.

**Downstream impact:** DriveDetector-adjacent (coordinate with the A-9 lane; distinct concern).

---

### US-433: PowerMonitor DB-write path activation — UpsMonitor → power_log (F-050, verify-first)
**Description:** As the system, I want the UpsMonitor readings written to `power_log`, so power history is captured.

**Acceptance Criteria:**
- [ ] **Verify-first:** re-query the live Pi — `power_log` may already be populating (Sprint 50 US-412 synced it). If the write path is live + healthy, close with evidence.
- [ ] If gaps remain: activate/repair the UpsMonitor → `power_log` write path (VCELL/SOC/CRATE/power_source per poll).
- [ ] Bench-verifiable (rows appear in `power_log`); `ruff check` passes.

**Downstream impact:** Feeds `power_log` (now server-synced per US-412).

---

### US-434: drain_event close-on-poweroff targeted fix (F-062)
**Description:** As the system, I want drain_event rows to close cleanly on poweroff, so drain records aren't left open.

**Acceptance Criteria:**
- [ ] **Verify-first:** re-query recent `drain_event` rows for stuck-open records post-poweroff. If clean, close with evidence.
- [ ] If open-leak persists: a targeted close-on-poweroff fix in the shutdown path (mind the SS-T5 `ShutdownSequencer` — the orchestrator was retired).
- [ ] Unit/bench test; `ruff check` passes.

**Downstream impact:** Shutdown path (ShutdownSequencer); coordinate with the power_watch pipeline.

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

## 5. Open Questions (for Atlas's review)

1. **Placement:** derived signals (US-436) + cross-drive tool (US-438) — confirm server-side (Pi-emitter/server-authority), not Pi.
2. **US-432 (drive_detect idle-poll)** — does this touch the A-9 DriveDetector lane enough to need your gate, or is it a contained poll-cadence fix?
3. **US-434 (drain_event close)** — confirm the ShutdownSequencer is the right seam (orchestrator retired SS-T5).
4. Any of the verify-first items (US-433/434/437) you expect are already-resolved?

## Action Items (NOT sprint stories)

- **Route Atlas for F-104 (Server-Side Analytics Authority) design gate** — for Sprint 54 grooming.
