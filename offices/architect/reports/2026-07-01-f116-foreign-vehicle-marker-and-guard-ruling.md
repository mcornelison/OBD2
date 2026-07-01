# Atlas Ruling — F-116 foreign-vehicle contamination: marker enum + ingest guard

**By:** Atlas (Architect) · **Date:** 2026-07-01 · **Requested by:** Marcus (`2026-07-01-from-marcus-f116-foreign-vehicle-design-gate`) · **Source:** Spool `2026-06-30-…-foreign-vehicle-contamination-drive33`
**Scope:** the US-424 (F-116) design-pending items in the Sprint 51 / V0.29.5 PRD. Data-integrity, not engine-safety. Verified against shipped code.

## Verified facts
- `data_source` enum SSOT = `src/pi/obdii/data_source.py` `DATA_SOURCE_VALUES` (`real, replay, physics_sim, fixture`) → the CHECK string propagates to all 5 Pi capture tables + `drive_summary`. Server has its own mirror.
- `data_quality` enum SSOT (server) = `src/server/analytics/drive_statistics_compute.py` `DRIVE_STATISTICS_DATA_QUALITY_VALUES` (`full, sparse, below_threshold, attribution_anomaly`) with a **divergence assertion (`:101`)** already enforcing classifier↔model agreement.
- **No negotiated-protocol accessor exists** in the codebase (no ELM327 `ATDPN`/protocol-id plumbing) — only the sample-rate signal is cheaply available today.
- Shared OBDLink LX was used on **both** vehicles (drive 33 = Explorer) — a device/dongle-MAC allowlist could not have distinguished them.

## Ruling

### 1. Marker enum — `data_source='foreign'` (primary) + `data_quality='foreign_vehicle'` (drive-level)
- **`data_source='foreign'`** added to the `data_source.py` SSOT `DATA_SOURCE_VALUES` (one edit → all 5 table CHECKs) + **mirrored on the server** `data_source` CHECK. **Decisive rationale:** every real-data tuning query already filters `WHERE data_source='real'`, so `='foreign'` excludes contaminated rows with **zero consumer changes**. Semantics: *real capture, non-target vehicle* — honest and distinct from real/replay/sim/fixture. **NOT `'fixture'`** (Spool's correct objection: fixture-cleanup could delete the evidence). This is the primary row-level exclusion axis.
- **`data_quality='foreign_vehicle'`** added to the `drive_statistics_compute.py` SSOT set + the model enum (the `:101` assertion guards them) for **drive-level** honesty — self-describing beyond the ambiguous `is_real=0`; another exclusion reason alongside `attribution_anomaly`.
- **A-4:** both are forward-only CHECK migrations applied **identically on both tiers** (define once per SSOT, mirror the other tier). Re-tag drive 33 via **Spool's SQL** (his lane) once the enums land: `realtime_data.data_source='foreign'` + `drive_summary.data_quality='foreign_vehicle' WHERE drive_id=33`. **Re-tag, never delete** — evidence preserved.

### 2. Ingest guard — bus-rate sanity check (primary); NOT allowlist, NOT VIN
- **PRIMARY: sustained bus-rate check** — aggregate sample rate over a rolling window > **~7/s** (Eclipse ISO 9141-2 K-line ceiling ~6.3/s, Spool Session 26) → flag foreign. Cheap, hardware-grounded, no new plumbing, no vehicle cooperation.
- **Device/dongle-MAC allowlist — RULED OUT:** the *same* OBDLink served both vehicles; it would not have caught drive 33. Don't build it.
- **VIN guard — RULED OUT** (Spool/Marcus): Eclipse ECU MD326328 is Mode-09 silent (no VIN), the Explorer returns one → VIN-presence is backwards.
- **Protocol-ID (stronger, deferred):** the ELM327 knows the negotiated protocol (ISO 9141-2 K-line vs **ISO 15765 CAN** = definitively non-Eclipse), available **at connect** — faster than waiting for sustained rate, and it could *prevent minting a foreign drive at all*. But there's **no protocol accessor today** → new ELM327 querying. **Recommend as future hardening, not required this sprint.**
- **Correctness:** measure a **sustained windowed** rate (not an instantaneous burst) so a legit Eclipse drive is never false-flagged; on trip, **flag/quarantine (mark `foreign`), NEVER silently delete** — a guard that deletes on suspicion is the anti-pattern (a false positive would destroy real telemetry). Honest-instrument: preserve, mark, exclude.

### 3. Guard placement — both, layered (the A-9 defense-in-depth pattern)
- **Pi-side PRIMARY:** on a sustained-rate trip, retro-tag the open drive's rows `data_source='foreign'` and **do not sync them as real**. (Prevent-mint-at-connect needs the faster protocol-ID signal → future; the rate check supports *mark-foreign-on-detection* now.) **A-9 interaction note:** this is the DriveDetector opening a "drive" for a non-Eclipse vehicle — a *distinct* concern from A-9 attribution-within-Eclipse, but the same connection-edge locus. Note it; do not couple the fixes.
- **Server-side BACKSTOP tripwire** (like `detect_overlapping_drives`): flag any synced drive whose aggregate rate exceeds the K-line ceiling → `data_quality='foreign_vehicle'`. Catches historical rows or a Pi-guard regression; server = authority. 
- **Sizing (Marcus's lane):** the marker enums + the Pi-side rate guard are the must-haves; the server tripwire is belt-and-suspenders — recommend, but it can follow if US-424 sizes tight.

### Rule-10 DoD
CHECK-enum changes to the cross-tier data contract are load-bearing → `specs/architecture.md` data-contract section documents the `foreign`/`foreign_vehicle` values + the bus-rate guard, in-sprint (US-425 already carries the doc-sync — ensure it names these).

## Disposition
- US-424 revised inline to this ruling (`[ATLAS]`-attributed); PM note routed. Rule-13 on freeze as usual.
- The rest of the PRD reviewed sound: **US-416/US-417 faithfully build to my 2026-07-01 snapshot-sync ruling** (recorded_at cursor, natural-key upsert, A-4 single-definition guard, leave dtc_freeze_frame alone) — verified against the story ACs.

— Atlas
