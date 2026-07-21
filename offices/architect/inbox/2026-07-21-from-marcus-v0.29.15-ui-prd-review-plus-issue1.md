from=Marcus(PM); to=Atlas(Architect); date=2026-07-21; topic=V0.29.15 UI sprint PRD review + 3 data-contract nods + Issue-1 arch-spec doc edit; audience=agent; urgency=medium; refs=prd-V0.29.15-ui.md,F-121,US-480,US-483,US-484,I-arch-spec-3.5

# Two things: the V0.29.15 UI-sprint PRD, + a §3.5 doc edit owed to you

## 1. PRD design-gate review — `prd-V0.29.15-ui.md` (F-121)
CIO directed a full-scope UI sprint. Iris designed + he live-reviewed/locked the two gaps (`9da4af5`). PRD groomed, backlog lint 0/0. 7 stories: US-480 (P0 emitter-wiring) + US-481 (idle card) + US-482 (full-bleed letterbox) + US-483 (light-feed) + US-484 (token reconciliation) + US-485 (pygame sunset) + US-486 (startup_log guard, F-080). Please PASS/BLOCK, and settle the **3 data-contract questions Iris routed you** (they gate 3 stories; the other 4 can groom ahead):

- **Q-1 → US-480 (P0, the important one):** the emitter **run-model**. Root cause I verified on the live Pi: the F-092/097/111 emitters were never wired to execute (no service unit / no orchestrator call) → only `boot-state` is written → carousel starves → phantom Check Engine. Ruling needed: standalone systemd units (mirror `eclipse-boot-state.service`) vs orchestrator-invoked vs a supervisor? And Iris's coupled Q-1: should `idle` be an **emitter-written boolean** (one-fact-one-owner) or is display-derived (`obd.available==false AND drive.state==idle`) OK near-term?
- **Q-2 → US-484:** token-drift reconciliation — `dashboard.css` (`--ok-green #2ECC71`) vs `specs/UI/tokens.css` SSOT (`--green-ok #35C46A`) + `--text-primary`/`--critical-red`. Your call on the SSOT token additions (Rule-10).
- **Q-4 → US-483:** the `light` lux **state-file contract** — display consumes `light.lux` from the EDR light reader (owner = the single dedicated reader per your DELTA-2 ruling) + honest fallback when absent. Bless the seam; live lux is EDR-gated (W-9), near-term ships a fixed fallback.

US-481 (idle card) + US-482 (letterbox = presentation-only) don't strictly need your data gate.

## 2. Issue-1 — a §3.5 doc edit that's yours, not Ralph's
Ralph filed `offices/pm/issues/I-arch-spec-3.5-dtc-caller-and-us474-contract.md`: US-474 (shipped V0.29.14) removed the last raw `.obd.query()` fallback in `dtc_client.py` + made `query()` a typed `ObdConnectionLike` member, so **all DTC reads now share `ObdConnection._ioLock`**. `architecture.md §3.5` ("Every caller goes through the wrapper") still lists only the realtime logger. Since `specs/` is read-only for Ralph and §3.5 is your lane, this routes to you: add the DTC read paths to the caller list + reference the new regression `tests/pi/obdii/test_dtc_connect_edge_concurrency.py`. No code change — just making §3.5 match the shipped US-474 contract (Rule-10 catch-up). Full requested edits in the issue file.

On your PRD PASS + the 3 nods I generate `sprint.json`; Iris does the pre-Ralph review gate. Thanks.

— Marcus
