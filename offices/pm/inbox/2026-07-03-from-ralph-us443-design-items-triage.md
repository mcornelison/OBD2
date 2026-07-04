# US-443 triage — Tester V0.28+ data-profile DESIGN items (D-1…D-8)

**From:** Rex (Ralph / Dev) → Marcus (PM); cc-for-ruling Atlas (Architect), Spool (Tuner SME)
**Date:** 2026-07-03
**Story:** US-443 (Sprint 54 / V0.29.8), parent F-082
**Sources read:** `offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md` (the 8 D-items) · `offices/pm/backlog/F-082-tester-v028-data-profile-findings-rollup.md` · `offices/pm/prds/prd-V0.29.8.md`
**Audience:** PM + CIO (human return to this) → Markdown.

## TL;DR — answers PRD Open-Q#3 ("which are Ralph-buildable vs need Spool/Atlas input")

**0 of 8 are cleanly Ralph-buildable in Sprint 54.** All 8 are schema-contract or analysis-tier design decisions that (a) the **tester itself filed as "no fix needed now, just noting… for the V0.28 DB-arch discussion,"** (b) F-082 says "become stories under B-076's PRD" (the server schema-normalization epic), and (c) **this PRD already defers F-104 + schema-normalization to Sprint 55.** Shipping any of them requires an **Atlas architecture ruling** (D-1/2/3/4/7/8), a **Spool analysis-tier discovery** (D-6), or a **CIO/hardware decision** (D-5) — none is a code change Ralph can make without guessing, which Refusal Rule 1 forbids.

Per the AC ("implement the ready ones OR file/defer with rationale… do NOT guess") this note **is** the deliverable: each item triaged, none silently skipped. Recommend these graduate as Sprint-55 stories under **B-076 (server schema-normalization)** / **F-104 (server-authority)**.

## Buildable-vs-needs-input split

| Item | Disposition | Blocked on | Sprint-55 home |
|---|---|---|---|
| D-1 statistics vs drive_statistics consolidation | **DEFER** | Atlas ruling | F-104 (drive_statistics writer = US-446, already deferred) |
| D-2 connection_log drive-lifecycle → drives | **DEFER** | Atlas ruling (load-bearing) | B-076 |
| D-3 realtime_data O2 param-name normalize | **DEFER** | Atlas ruling + migration | B-076 |
| D-4 `unit` column overloaded (status + `volt`/`V` drift) | **DEFER** | Atlas/decision (likely intentional) | B-076 |
| D-5 Pi `static_data` empty — populate or drop | **DEFER** | CIO/hardware decision | B-076 (+ TD-061 Pi migration ledger) |
| D-6 analysis-output tier empty (8 tables) | **DEFER** | Spool + Atlas discovery | F-104 / F-083 |
| D-7 Pi-only tables sync scope | **DEFER** | Atlas ruling | B-076 / F-104 |
| D-8 drive_summary column families + drive_annotations FK gap | **DEFER** | Atlas ruling | B-076 |

## Per-item rationale (grounded in code evidence)

### D-1 — `statistics` (per-PID-per-profile) vs `drive_statistics` (per-PID-per-drive) overlap
Design call that "gates B-075." `drive_statistics` is empty; its writer is **US-446, which this PRD explicitly DEFERS to Sprint 55 under the F-104 gate** (Atlas: derived analytics in his server-authority lane; Pi-side-now risks F-104 churn). Consolidate-vs-emit-both is exactly the kind of derived-analytics authority call F-104 owns. **Owner: Atlas.**

### D-2 — `connection_log` mixes BT-connection + drive-lifecycle events
Moving `drive_start`/`drive_end` out of `connection_log` into `drives` is a cross-tier schema migration on a **load-bearing** table: `connection_log` is read by the DriveDetector attribution path (the `detect_overlapping_drives` / `attribution_anomaly` tripwire, per MEMORY). Restructuring it without an architecture ruling risks the A-9 dual-attribution class of bug. **Owner: Atlas; home B-076.**

### D-3 — `realtime_data` O2 parameter-name inconsistency (`O2_B1S1` vs `O2_BANK1_SENSOR2_V`)
Both are **live**: `O2_B1S1` is enabled in `config.json` (`logData: true`, PID 0x14) and defined in `config/parameters.py` + `obd_parameters.py`; `O2_BANK1_SENSOR2_V` is defined in `decoders.py` (PID 0x15, cmd `O2_B1S2`). They are different sensors in two naming styles. Normalizing = renaming an emitted `parameter_name`, which is a **data-contract change**: it splits historical `realtime_data` rows and, per the explicit comment in `decoders.py`, **`O2_BANK1_SENSOR2_V` is keyed by the US-229 DriveDetector silence-check regression test** — renaming it breaks that test. Requires a canonical-name ruling + a migration strategy. **Owner: Atlas; home B-076.**

### D-4 — `unit` column overloaded as enum label
`FUEL_SYSTEM_STATUS` writes `unit ∈ {CL, OL, OL-drive}`, `MIL_ON` writes `unit='OFF'`; plus a `volt` (O2_B1S1) vs `V` (O2_BANK1_SENSOR2_V) capitalization drift. The tester's own hedge: **"If the status-vs-unit overload is intentional (it's how python-obd represents these), at least make it consistent."** Whether the overload is intentional and what the canonical unit string is (`volt` is python-obd/pint-native; `V` is hand-written in `decoders.py`) are design decisions; changing emitted unit strings is again a contract change vs historical rows. **Owner: Atlas/decision; home B-076.**

### D-5 — Pi `static_data` empty (0 rows) — populate or drop
`StaticDataCollector` (`vehicle/static_collector.py`) exists and is exported, **but is NOT invoked anywhere in the orchestrator runtime path** (grep of `orchestrator/` = 0 hits), and even if wired it gates on `shouldCollectStaticData()` → a readable **VIN**, which the current ECU does not answer (Mode 09 silent, per MEMORY "ECU Identity"). So "populate" needs *both* wiring the collector into the loop *and* an ECU that answers VIN (hardware); "drop" needs removing the subsystem *and* a Pi-side migration — but **the Pi has no `schema_migrations` table** (finding N-3, already tracked as `TD-061`). Not a triage-scope code fix either direction. **Owner: CIO/Atlas decision; depends TD-061.**

### D-6 — entire analysis-output tier empty (8 tables, 0 rows after 11 drives)
`ai_recommendations`, `analysis_history`, `anomaly_log`, `alert_log`, `trend_snapshots`, `calibration_sessions`, `baselines`, `drive_statistics`. The tester flags this as the **"discover-first"** / "is this whole feature even wired" question — the Spool/Ollama analysis layer may never have run end-to-end. This is squarely **F-104 (server-side analytics authority)** + **F-083 (Mahalanobis, needs a clean baseline → needs F-117 capture working first)**, both of which this PRD defers to Sprint 55. **Owner: Spool (analysis-tier) + Atlas (F-104).**

### D-7 — `power_log`/`startup_log`/`pi_state`/`static_data` are Pi-only (never sync)
Whether the granular forensic tables should sync to the server-of-record is a sync-scope architecture decision that couples to D-2/D-8 and the F-104 server-authority model. **Owner: Atlas; home B-076/F-104.**

### D-8 — `drive_summary` overlapping column families + `drive_annotations` FK gap
`device_id`/`source_device`/`source_id`/`drive_id` + `start_time`/`drive_start_timestamp`; and `drive_annotations.drive_id` can't join `drive_summary` (Pi id lives in `source_id`, `drive_summary.drive_id` is NULL). This is part of the `drive_summary`→`drives` rename in the server schema epic; collapsing the families is explicitly "part of US-326's pre-flight / the V0.28 rename." **Owner: Atlas; home B-076.**

## Recommendation to PM

1. **Accept the triage** and graduate D-1…D-8 as Sprint-55 stories under B-076/F-104 (they already have a traceability home in F-082 + the findings file).
2. If you want **any single item forced into a later Sprint-54 story**, D-4's `volt`→`V` unit-string drift and D-5's decision are the lowest-blast-radius candidates — but both still need a canonical-value ruling first, so I'd route them through Atlas rather than have Ralph guess.
3. No code shipped for US-443 (no `.py` touched) — this is by design: the disciplined outcome of a "triage the design smells" story where the tester's verdict was "no fix now" and the owning epic is deferred.
