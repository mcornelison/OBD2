# Project Roadmap

**Project**: Eclipse OBD-II Performance Monitoring System
**Last Updated**: 2026-06-29 (Session 50 — full rewrite; prior version was a 2026-04-11 pre-V0.24 relic on the retired Phase/B-XXX scheme)
**Target Platform**: Raspberry Pi 5 (edge) + Chi-Srv-01 (server)

> This is the **high-level delivery roadmap** — epics, the release-chain model, and near-term priorities. Story-level detail lives in `offices/pm/backlog.json` (single source of truth; no duplication per PM Rule 4). Session history lives in `offices/pm/projectManager.md`. Tuning/vehicle vision lives in `offices/tuner/knowledge/` (Spool-owned).

---

## Where we are now (2026-06-29)

**Release state** (dev/main branching workflow — `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`):
- **`main` = `V0.28.2`** — last fully-validated stable (merged 2026-06-05; drive-27 single-attribution IRL drill passed).
- **`dev` = V0.29 chain** carrying:
  - **V0.29.0** — EDR dedicated-reader bus Slice 1 (E-006/F-110). Deployed, ships **dark** behind `pi.bus.enabled=false`; awaiting Pi flag-flip + byte-identical validation.
  - **V0.29.1 / Sprint 47 — IN FLIGHT** (Ralph executing on `sprint/sprint47-V0.29.1`): data-integrity hardening — A-9 DriveDetector RCA+fix, ECU lineage spine, sync quarantine, config de-dup.

**System** (3-tier): Pi 5 `10.27.27.28` (in-vehicle capture) → **Chi-Srv-01 `10.27.27.120`** (MariaDB `obd2db` + Ollama `llama3.1:8b`) → AI analysis. Architecture: **Pi = canonical raw emitter, server = analytics authority** (B-104).

**Vehicle**: 1998 Eclipse GST (4G63 turbo). Driving (Drive 27+) on the **new modified-EPROM ECU `MD326328`** (swapped ~2026-05-22, drives ≥25; prior factory ECU `MD346675` for drives ≤24). SPEED reads true (factor 1.0 on both ECUs — the "2× drift" was a km/h-as-mph mislabel, GPS-resolved). **ECMLink V3 owned, not yet installed** (planned summer 2026). Live OBD-II data flowing to the server; baselines establishing.

---

## How we work

- **Release chains**: a `V0.X` chain = a `V0.X.0` minor sprint + stacked `V0.X.N` patch sprints, integrated on `dev`. When the whole chain is IRL-validated, `/chain-validated` merges `dev`→`main` and tags `V0.X.N`.
- **Sprints**: each runs on its own branch off `dev`; PM (Marcus) freezes the contract (`sprint.json` + `bigDoDHash`), Atlas Rule-13 signs off, Ralph executes, PM merges at close via `/sprint-deploy-pm`.
- **Backlog v2**: Epic (E-) > Feature (F-) > Story (US-). Typed stories (issue/blocker/tech-debt/research/housekeeping/security) replace the old I-/BL-/TD- intake.
- **Team**: Marcus (PM/orchestration) · Atlas (architecture + design gate) · Ralph/Rex (dev) · Spool (tuning SME) · Argus (QA) · Iris (UI/UX). CIO ratifies + drives hardware/IRL.

---

## Epic roadmap

| Epic | Theme | State + next |
|------|-------|-------------|
| **E-001** | UI/UX Polish | **CIO-driven near-term line.** F-103 splash **groom-ready** (the required-first chromium-kiosk runtime); F-092 System Status + F-097 Battery Health carousel + F-111 DTC viewer/Mode-04 clear **pending Atlas design-gate signoff**. Sequence: F-103 → carousel → cards → DTC Card 5. Staging plan: `prds/prd-uiline-draft.md`. |
| **E-002** | Data Pipeline & Analytics | **Active (Sprint 47).** A-9 DriveDetector (F-107) + ECU lineage (F-108) + sync hardening (F-076). Direction: server-side analytics authority (F-104, B-104). Pending: derived signals, baselines, sync-cadence cleanups. |
| **E-003** | Tuning Intelligence | Mostly **gated on ECMLink + accumulated clean data**. GEM dashboard-intelligence items (F-087..F-095), MAP PID (F-074), ECMLink integration (F-025). Spool-led. |
| **E-004** | Infrastructure & Deploy | Active: Pi pipeline (F-037), auto-sync/shutdown (F-043), config-driven addresses (F-044). Pending: Pi self-update (F-047), fuse-box power (F-063), hostname cleanup `Chi-Eclips-Tuner`→`chi-eclipse-01` (F-102). |
| **E-005** | Reports & CLI | Pending: Excel export (F-041), audio reports (F-091), Ollama fallback docs (F-003). |
| **E-006** | **EDR / Black-Box Recorder** | **Emerging V0.3x+ multi-sprint direction.** Slice 1 bus shipped (F-110, dark). Phases filed: **F-112 ECMLink feasibility spike** + **F-113 bus-contract design** (both **hardware-independent → groomable now**); **F-114 IMU/light channels** + **F-115 event-vault+triggers** (hardware-gated). Sensors **hardware-installed 2026-06-27** (ahead of schedule); CIO mid-wire, gate = `i2cdetect` 29/36/69. Atlas Watch List A-14. |
| **E-OPS** | Operational Hygiene | Standing typed-story home: power/UPS, sync hygiene, connection-log noise, schema cleanups, DTC freeze-frame (F-108/F-109), arch-doc maintenance (F-105). |

---

## Near-term priorities

1. **Finish + validate Sprint 47 / V0.29.1** (in flight) → A-9 IRL re-gate (CIO-gated: short/back-to-back + key-on-after-missed-close + deploy double-start) → merge dev → deploy/test → `main` on pass.
2. **Validate Sprint 46 / V0.29.0** — Pi flag-flip (`pi.bus.enabled=true`) + byte-identical `realtime_data` → `/sprint-validated`. Fold into the Sprint-47 deploy window.
3. **UI line** — groom **F-103** (ready now; unblocks the whole line); carousel + DTC viewer await Atlas design-gate signoffs.
4. **EDR (next themed direction)** — groom the **hardware-independent** foundation now: ECMLink feasibility spike (F-112) + bus-contract design (F-113). Hardware integration (F-114/F-115) once `i2cdetect` passes. Staging plan: `prds/prd-edr-next-draft.md`.

---

## Long-term vehicle / tuning vision

The north star is unchanged: **collect OBD-II data → AI analysis on Chi-Srv-01 → inform ECU tuning via ECMLink V3**, then track tuning impact drive-over-drive. The detailed multi-phase vehicle-modification roadmap (pre-hardware → live OBD-II → ECMLink+wideband → E85+full-tune → mature/edge-intelligence) is **Spool-owned** — see `offices/tuner/knowledge/`. Current position: **live OBD-II collection on the modified-EPROM ECU, pre-ECMLink-install.**

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-29 → 2026-04-11 | Marcus (PM) | Original roadmap (Phase/B-XXX scheme): Phases 1–7, Pi-deployment items B-012..B-032, Spool 5-phase tuning roadmap, Chi-Srv-01 spec. Superseded. |
| 2026-06-29 | Marcus (PM) | **Full rewrite (Session 50).** Replaced the retired Phase/B-XXX model with the backlog-v2 epic roadmap + the V0.X release-chain/dev-main workflow. Refreshed to current state: `main`=V0.28.2, `dev`=V0.29.1 (Sprint 47 in flight), chi-srv-01=`.120`, new ECU `MD326328`, SPEED=1.0. Added E-006 EDR direction (sensors installed). De-duplicated against `backlog.json` (now the story-level SSOT). |
