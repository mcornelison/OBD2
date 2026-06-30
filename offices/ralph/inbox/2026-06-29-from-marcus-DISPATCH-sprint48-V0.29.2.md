from=Marcus(PM); to=Rex(Dev); date=2026-06-29; topic=DISPATCH Sprint 48/V0.29.2 -- Pi UI foundation + 2 bug fixes (bench-only); audience=agent; urgency=high; refs=US-393,US-394,US-395,US-396,US-397,US-398

# Marcus -> Rex: Sprint 48 / V0.29.2 DISPATCHED

Branch **`sprint/sprint48-V0.29.2`** forked from `dev`, pushed, upstream set; checkout is on it. **Atlas Rule-13 PASS** (CIO-confirmed). **Argus + Atlas signed off the PRD.**

## Contract
`offices/ralph/sprint.json` -- sprint 48, V0.29.2, 6 stories. Frozen; do not edit the contract.

## Build order
**F-103 splash is sequential** (the boot runtime underpins the rest):
1. **US-393 boot splash** -- **start here.** chromium kiosk + `eclipse-boot-state.service` + `eclipse-states-http.service` :9899 + token SSOT + the boot splash render.
2. **US-394 shutdown splash** (deps US-393) -- ShutdownSequencer phase-emit hook + **Rule-10 `specs/architecture.md` §10.6 update in-sprint (Atlas BLOCKs otherwise)**.
3. **US-395 deploy integration** (deps US-394) -- fold the F-103 units into `deploy-pi.sh`, WARN-not-BLOCK.
4. **US-396 defects** (deps US-395) -- D-1/2/3 + V-1/V-2 install checks.
- **Independent (any order):** **US-397** fix `sync_now.py` import break (+ batch-audit Pi-side scripts) · **US-398** fix simulate duplicate `(timestamp, parameter)` rows (rule test-fidelity vs data-quality, then fix).

## Atlas C-5 design-gate conditions (in US-393/394/395 DoD -- do NOT skip)
The `/run/eclipse-obd/states/` dir + the F-103 units have a RuntimeDirectory-lifecycle hazard (same EPERM/ENOENT crash-loop class as the A-9 guard C-5):
- **US-393:** `/run/eclipse-obd/states/` must exist at boot **independent of `eclipse-obd.service`** (shared `RuntimeDirectory=eclipse-obd` OR a `tmpfiles.d` entry; NOT the deploy-time `install -d` which tmpfs wipes on reboot). Reconcile with eclipse-obd's remove-on-stop.
- **US-394:** `shutdown-state` must survive **after `eclipse-obd.service` has stopped** (its RuntimeDirectory is removed on stop) -- eclipse-states-http + the states dir must outlive it during shutdown.
- **US-395:** the deploy installs the boot-durable provisioning + `architecture.md` documents the `/run/eclipse-obd/states/` ownership+lifecycle SSOT across the three units.

## Validation = BENCH ONLY (CIO waived drive reqs)
Boot/shutdown drills + unit/integration tests. The C-5 acceptance needs a **COLD REBOOT** (US-393/395) + a **SHUTDOWN-WITH-ECLIPSE-OBD-ALREADY-STOPPED** drill (US-394) -- warm drills are insufficient. NO drive drills.

## Notes
- Commit to THIS branch (shared-checkout: commit-immediately, never push-to-main; I integrate at close via `/sprint-deploy-pm`).
- Iris owns the F-103 splash design (spec `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` v1.2, §9 acceptance); Atlas owns the C-5 / RuntimeDirectory architecture.
- The carousel + DTC viewer are NEXT sprint (Sprint 49, pending Atlas's design-gate) -- F-103 here is their prerequisite runtime.

CIO launches `ralph.sh` from his shell.

-- Marcus
