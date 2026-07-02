---
sprint: 52
version: V0.29.6
status: draft
createdAt: 2026-07-01
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-001, E-002, E-OPS
feature: F-098, F-061, F-060, F-103, F-111
theme: BL-014/BL-015 carry-forward (power-mode + SoC%) + Pi display deploy-contract hardening
validationMode: BENCH ONLY (fixture/DOM + Pi bench rigs + DB-column checks + deploy-smoke + UPS-drain rig -- NO drive drills; Bug3 live-data is a separate car/QA gate)
selectedStories: [US-421, US-426, US-427, US-428, US-429, US-430]
---

# PRD: Sprint 52 / V0.29.6 — BL-014/015 carry-forward + Pi display hardening

| Field | Value |
|---|---|
| Sprint | 52 |
| Version | V0.29.6 (patch on the V0.29 chain) |
| Branch | `sprint/sprint52-V0.29.6` (forks from `dev`) |
| Validation | **BENCH ONLY** — fixture/DOM, deploy-smoke, UPS-drain rig, DB introspection. Bug 3 live-data = separate car/QA gate. |
| Story range | US-421 (re-groomed) + US-426…US-430 (6 stories) |

## 1. Introduction / Overview

Two threads: (A) the **BL-014/BL-015 carry-forward** — the 3 stories that blocked in Sprint 51, now Atlas-ruled + CIO-ratified; and (B) **Pi display deploy-contract hardening** — Atlas wrote + committed the blank-screen fixes (Bugs 1/2/4) CIO-supervised; Ralph reviews, adds test coverage, and lands the proper Bug-2 fix + the Bug-3b empty-state takeover fix.

Rulings: `offices/architect/reports/2026-07-01-bl014-bl015-power-mode-soc-rulings.md`. Display finding: `offices/architect/findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`.

## 2. Goals

- Land the power-mode badge on a static config-key SSOT (honest `unknown`, GPIO-swap-ready seam).
- Record register SoC% into a durable both-tier `_soc_pct` column, migration-first, with the US-234 cold-start guard.
- Make `deploy-pi.sh` kiosk install regression-covered + OS-version-proof (Bug-2 proper fix).
- Fix the empty-state CHECK-ENGINE takeover mis-fire.
- Zero drive drills.

## 3. User Stories

> Build order (deps): **US-426 (schema) BEFORE US-427 (wiring)** — the ruling inverts the old order (can't write `_soc_pct` before it exists). US-421 / US-428 / US-429 independent.

---

### US-421: Power-mode badge — `PowerModeProvider` config-key SSOT (BL-014, re-groomed)
**Description:** As the CIO, I want the carousel power-mode badge sourced from a real SSOT, so it shows in-car vs wall-power honestly.

**Acceptance Criteria:**
- [ ] New single `PowerModeProvider` in `src/pi/power/` reads config `pi.power.mode ∈ {car,wall,unknown}`, **default `unknown`** (added to `validator.py` DEFAULTS + `config.json`); it is THE single acquisition path (no second path — there are zero today).
- [ ] Wires `powerMode` into `system_status_emitter.buildSystemStatusState` (the existing pass-through param) → `carousel.js powerTile` renders CAR/WALL/unknown.
- [ ] Undeterminable/stale/invalid config → `unknown`, **never a confident wrong mode** (honest-instrument).
- [ ] Seam designed so acquisition can later swap config→GPIO behind the same SSOT interface with zero consumer change (future; NOT this sprint — do not build GPIO).
- [ ] NOT the `power_source_provider` (that's AC-vs-battery, the wrong fact).
- [ ] Fixture/DOM test with mocked config states; `ruff check` passes.

**Downstream impact:** New provider + one config key; read-only consumer wiring.

---

### US-426: `battery_health_log` SoC% schema — drop legacy `_soc` + add `_soc_pct`, one migration (BL-015, migration-first)
**Description:** As the system, I want one forward-only both-tier migration that retires the legacy `_soc` columns and adds dedicated `_soc_pct` columns, so SoC% has a durable home.

**Acceptance Criteria:**
- [ ] ONE forward-only migration, **both tiers identical (A-4)**: drops legacy `start_soc`/`end_soc` AND adds `start_soc_pct`/`end_soc_pct` (Float, nullable). Pi SQLite (CREATE-AS-SELECT-DROP-RENAME) + server MariaDB (`DROP COLUMN` + `ADD COLUMN`) + `models.py` + sync mapping.
- [ ] **Deployed AND verified** via schema introspection on both tiers; consumers migrated to `start_vcell_v`/`end_vcell_v` + the new `_soc_pct`; lock-down tests updated.
- [ ] This MERGES old US-423 (drop) with the `_soc_pct` add — do them together (same table).
- [ ] `ruff check` passes.

**Downstream impact:** Both-tier schema change; runs BEFORE US-427.

---

### US-427: Wire register SoC% into the bench drain-CLI + cold-start guard (BL-015, deps US-426)
**Description:** As the CIO, I want the drain-test CLI to record real MAX17048 SoC% into `_soc_pct`, guarded against the cold-start calibration window.

**Acceptance Criteria:**
- [ ] `scripts/record_drain_test.py` reads `UpsMonitor.getBatteryPercentage()` (register SoC%) into `start_soc_pct`/`end_soc_pct` (NOT the operator-typed voltage slot; NOT a sequencer drain-event — the ruling picked the bench CLI).
- [ ] **Cold-start guard (US-234):** SoC% within the ~3-min MAX17048 calibration window → NULL/flagged, **never a garbage percent**; guard lives in the recording path.
- [ ] **Cleanup (TD-058):** remove the dead `batteryHealthRecorder` reference in `hardware_manager` (stored, never called since the SS-T5 orchestrator deletion).
- [ ] Bench drill (UPS-drain rig) shows `_soc_pct` populated on a closed row; a cold-start-window open records NULL not garbage.
- [ ] `ruff check` passes.

**Downstream impact:** CIO-facing tool behavior change; deps US-426's columns.

---

### US-428: Harden `deploy-pi.sh` kiosk install — test coverage + Bug-2 proper fix (display finding, Bugs 1/2/4)
**Description:** As the CIO, I want the kiosk deploy fix regression-covered and OS-version-proof, so the Pi never silently re-blanks.

**Acceptance Criteria:**
- [ ] Review Atlas's committed `step_install_ui_kiosk_units` + `eclipse-kiosk-no-blank.conf` (`8f6bb58`); add **deploy-smoke test coverage** (the step runs the kit installers, detects the seat0 graphical session, presence-gates absent kits WARN-not-BLOCK).
- [ ] **Bug-2 proper fix:** the UI-kit installer gains a **V-3 binary check** that substitutes the real chromium path (`chromium` vs `chromium-browser`) into the unit template (like it substitutes `User=`), so it's OS-version-proof WITHOUT the `/usr/bin` symlink shim.
- [ ] Rule-10: `architecture.md` deploy section documents the kiosk-install contract (Bug-1/2/4).
- [ ] `bash -n deploy-pi.sh` clean; `ruff check` passes on any touched `.py`.

**Downstream impact:** Deploy-path hardening; removes the symlink shim once V-3 lands.

---

### US-429: Fix empty-state CHECK-ENGINE takeover mis-fire (display finding, Bug 3b)
**Description:** As the CIO, I want the DTC takeover to NOT fire on empty/no-data state, so a fresh boot with no OBD doesn't show a jumbled CHECK-ENGINE screen.

**Acceptance Criteria:**
- [ ] The full-screen DTC severity takeover (US-405) does NOT trigger when the dtc state is empty/absent/unpopulated — only on a real retrieved code.
- [ ] Empty/loading state renders the normal carousel (honest-instrument; no jumbled layout).
- [ ] Fixture/DOM test: empty dtc state → no takeover; a real MAJOR code → takeover (regression both ways).
- [ ] `ruff check` passes.

> Bug 3a (carousel live-data with the car connected) is a **separate Argus/Iris car-validation gate**, not this story.

**Downstream impact:** Carousel takeover logic; guards the empty case.

---

### US-430: Sprint 52 documentation sync (Rule-10)
**Description:** As the PM, I need docs to reflect the sprint's schema/config/deploy changes.

**Acceptance Criteria:**
- [ ] `architecture.md` updated for the `_soc_pct` schema + `pi.power.mode` config + the kiosk-deploy contract (if not covered in-story).
- [ ] New config key `pi.power.mode` documented in `CLAUDE.md`.
- [ ] `regression_manifest.json` reflects F-098/F-060/F-061/F-103/F-111 status.
- [ ] All spec docs current; no stale references.

**Downstream impact:** Docs only.

## 4. Non-Goals (Out of Scope)

- **GPIO power-mode sense line** — future; this sprint is config-key only.
- **Sequencer drain-event recording** — ruled out (bench-CLI path chosen).
- **Bug 3a live carousel data** — Argus/Iris car-validation gate, not a Ralph code story.
- **`/chain-validated`** — held until the display renders end-to-end WITH live car data (Atlas).
- **No drive drills.**

## 5. Open Questions

1. **(Resize)** US-426 (both-tier migration) + US-428 (deploy hardening) are the heavier ones — accept sizes or split? Decide at `/resize-sprint`.

## Action Items (NOT sprint stories)

- **AI (car/QA):** Argus + Iris validate Bug 3a (carousel live data with the car connected: eclipse-obd ready → splash yields → live cards) — the pending V0.29-chain bench validation.
