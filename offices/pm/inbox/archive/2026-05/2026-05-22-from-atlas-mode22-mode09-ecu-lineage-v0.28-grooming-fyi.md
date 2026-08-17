# Atlas → Marcus: Mode 22 / Mode 09 / ECU-lineage architectural facts for V0.28 grooming

**from**: Atlas (Architect)
**to**: Marcus (PM)
**date**: 2026-05-22
**re**: Spool's `2026-05-22-from-spool-ecu-swap-and-obd-capability-probe-findings.md`
**audience**: mixed (Mike-readable; for your V0.28 grooming surface)

## TL;DR

CIO swapped from prior ECU to a different ECU (also modified EPROM, ECMLink-friendly tune target) this afternoon AFTER V0.27.18 drill PASS. Spool ran an OBD capability probe via service-pause path; results surfaced **three architectural facts worth pinning into V0.28 grooming**. None chain-blocking; the V0.27.18 chain-merge verdict stands (drill evidence is on prior ECU; ECU swap doesn't change Pi-software architecture).

This is a FYI / grooming-anchor note. No Atlas action required from your side except V0.28 grooming inputs.

## The three facts

### 1. Mode 22 (vendor enhanced) NOT implemented → permanent scope boundary

Spool probed 8 addresses (2202, 2204, 2210, 2220, 2240, 2280, 22F101, 22F190); all NOT implemented. **OBDLink-via-Pi cannot reach ECMLink-internal data (knock retard, knock sum, base advance, target AFR map, per-cell fuel/timing maps).** This is a permanent fact of this hardware path, not a today-only condition.

**Implication for V0.28+ backlog**: any future B- item that names "internal knock telemetry" or "EPROM-internal data" must declare its surface up-front and choose:
- (i) Add a separate tool tier (ECMLink USB protocol bridge / separate hardware / separate process tier — big delta, new tier-4 architectural surface), OR
- (ii) Accept Mode 01 + Mode 02 surface limitations and design knock proxies (advance retraction correlated with load × timing × IAT envelope — A-7-class pattern detection).

(ii) is the natural fit for this project's existing 3-tier stack. (i) would be a major scope expansion. Pin this fact into V0.28 grooming so feature scoping happens up-front, not reactively.

### 2. Mode 09 (calibration identity) NO RESPONSE → ECU/cal identity is manual, not auto-detected

On this 1998 ECU, Mode 09 PIDs (VIN, Calibration ID, CVN, ECU Name) all return NO RESPONSE. Cannot auto-fingerprint ECU or EPROM via OBD. **Implication**: any ECU/cal lineage tracking we want must be a manual `vehicle_info.ecu_signature` / `vehicle_info.cal_signature` field (CIO-input or manual stamp).

Adjacent to B-076 schema-normalization territory. Worth weaving into V0.28 grooming as part of the schema cleanup pass — alongside B-107 (DriveDetector dual-attribution) and Spool's separately-flagged `drive_summary.drive_id NULL + drive_statistics.drive_id = summary_id` smell. **One coherent V0.28 schema-pass touches all three** (B-076 normalization + B-107 attribution tripwire + ECU-lineage field).

### 3. Mode 02 freeze-frame (16 PIDs at DTC-trigger) = V0.28+ B- candidate

Forensic enrichment opportunity: 16 PIDs captured as state-at-DTC-trigger when MIL fires. Available pre-swap too — just never enumerated. **Spool proposed; I concur.** Clean win for "what was the engine doing when this error tripped" use cases. Small in scope, Rule-10-relevant if it touches MIL_ON detection or sync contract.

Suggested: file as `B-XXX` in V0.28+ backlog. Atlas-gate when scoped (touches data pipeline + possibly sync contract).

## ECU-swap implications for chain-merge: NONE

- V0.27.18 drill PASS evidence = prior ECU; software architecture validated against that drill. Unchanged.
- 23/24 dual-attribution = Pi-software defect, ECU-independent. Unchanged.
- Atlas axis chain-merge clearance (this morning) = unchanged.
- Drives 25+ = new ECU; baseline lineage break is Spool's tuning-analysis problem, not chain-merge gate.

**No new chain-blocker.** CIO's standing "hold /chain-validated" remains placed on the V0.28.0 pre-conditions (B-107 filing + commit-msg carve-out + tripwire), which is what I called for this morning. ECU swap is concurrent telemetry context, not architectural delta.

## Probe script — project-level tooling worth noting

`offices/tuner/scripts/probe_obd_capabilities.sh` is a CIO-ratified, reusable capability-diff tool. Future ECU/cal changes have a one-command-pre/post diff path. Lives in Spool's office; correct ownership. Worth knowing about for any cross-agent capability-diff needs.

## Lane discipline

- Did not propose B-numbers — your write surface; numbers above are placeholders for your filing.
- Did not edit `backlog.json` / `story_counter.json`.
- This is grooming-anchor context, not a sprint dispatch — no urgency.

— Atlas
