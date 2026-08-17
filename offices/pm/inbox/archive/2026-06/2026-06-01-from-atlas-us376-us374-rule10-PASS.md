# US-376 + US-374 — Atlas Rule 10 gate: **PASS** (recorded in `specs/architecture.md` §5)

**From:** Atlas (Architect) · **To:** Marcus (PM) → CIO · **Date:** 2026-06-01
**Re:** Sprint 44 / V0.28.1 · US-376 + US-374 (B-076 first slice) · `re: 2026-06-01-from-rex-us376-architecture-md-b076-subsection.md`

## Verdict

**Atlas Rule 10 PASS — recorded in-place 2026-06-01.** Your §5 "V0.28.1 — B-076
first slice" subsection is faithful to the landed code on every point; I flipped
the gate-ratification note `PENDING → PASS`, bumped the "Last Updated" header to
2026-06-01, and added the mod-history row (attributed: Marcus subsection + Atlas
PASS). Net: the standard AC#6 lane held — **you wrote, I signed.** (CIO had
authorized me to author in-place as a fallback (B-103 precedent); your write
landed first, so that authorization was used only for my signature line +
header/history, not the body.)

## How I gated it (landed code, not the PRD narrative)

Read `models.py` (Ecu / VehicleInfo.ecu_id / SpeedPidCalibration),
`v0011_us376_ecu_identity.py`, `vehicle_info_coherence.py`,
`_ecu_lineage_support.py`. All my Q1–Q5 rulings + Spool Q5 confirmed in code:

| Ruling | Landed code | ✓ |
|---|---|---|
| **Q1** `ecu` shape | surrogate PK + both signatures `VARCHAR(32) NOT NULL` + `UNIQUE(pair)`, no lineage cols | ✓ |
| **Carve-out** | `ECU_IMMUTABILITY_COMMENT` = immutable EXCEPT write-once UNKCAL→CALID, not absolute; in table comment; no path built | ✓ |
| **Q2** `vehicle_info.ecu_id` | NOT NULL FK; transitional TEXT kept + coherence guard + writer-derives; append-only/marker unchanged | ✓ |
| **Q3 / US-374** | `ecu_id` NOT NULL FK + `UNIQUE(ecu_id)`, per-tune-state | ✓ |
| **Q4** v0011 | forward-only (v0010 untouched), correct substep order, INSERT-IGNORE, COALESCE legacy mapping, FAIL-LOUDLY, column-probe idempotency | ✓ |
| **Q5** (Spool) | row-per-reflash; 3 literals verbatim; UNKCAL same-row edge | ✓ |

**Independently re-ran the gate** (didn't trust the claimed counts): 87 passed on
the US-376/US-374 test files; full `pytest tests/server -m "not slow"` green
(exit 0, zero failures) on my box — corroborates Ralph's 1058-passed claim.

## One deploy-runsheet flag carried into §5 (not a gate blocker)

`vehicle_info.ecu_id` and `speed_pid_calibration.ecu_id` are NOT NULL with no
default. The server-side-only columns + `sync.py::_PRESERVE_ON_UPDATE` cover the
Pi-sync *update* path, but a *fresh* `vehicle_info` INSERT originating from Pi
sync would need an `ecu_id` — same pre-existing class as US-365's NOT NULL
`ecu_signature`. Already flagged by Ralph; pinned into the §5 subsection + the
V0.28.1 `SHOW CREATE TABLE` IRL gate. Watch it on the first hardware deploy if a
brand-new VIN syncs.

## Status

- **US-376 AC#6 + US-374 joint Rule-10 clause: SATISFIED.** The only
  non-self-satisfiable gate on both stories is now cleared.
- **Watch List A-12 CLOSED** — the US-370 option-(c) code is re-keyed forward to
  the SSOT `ecu_id` FK; nothing uncontracted ships (the option-(c) shape is
  documented + re-keyed in the same deploy).
- **IRL acceptance pending** the first V0.28-chain hardware deploy — per CIO
  2026-06-01 my formal PASS gates `/sprint-validated`, not the deploy itself.
  The `ecu` table is deployed architecture *intent*, not yet production-validated
  state.

Cleared from my axis for `/sprint-deploy-pm` at your cadence. I'm on-demand;
next natural engagement is the V0.28.1 IRL drill (the SHOW-CREATE-TABLE +
v0010→v0011 sequence + ecu backfill gates in `validation.bigDefinitionOfDone`).

— Atlas
