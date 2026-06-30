---
sprint: 48
version: V0.29.2
status: draft
createdAt: 2026-06-29
createdBy: Marcus (PM)
selectedStories: [US-393, US-394, US-395, US-396, US-397, US-398]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
epic: E-001
feature: F-103
theme: Pi UI foundation (boot/shutdown splash) + bug cleanup
atlasRule13: PENDING
validationMode: BENCH-ONLY (CIO waived drive requirements 2026-06-29; boot/shutdown + unit/integration drills only -- NO drive drills)
---

# PRD — Sprint 48 / V0.29.2 — Pi UI Foundation + Bug Cleanup

## Summary

A UI-foundation + cleanup sprint forking from `dev` (continues the V0.29 chain;
`main` stays at `V0.28.2`). Two threads:

1. **F-103 Pi splash (E-001/F-103)** — the boot + shutdown splash on the 3.5"
   display, backed by a **chromium kiosk + a localhost state server**. This is the
   **required-first runtime** the rest of the UI line (carousel, DTC viewer) depends
   on — it must land before any of that can be built (Atlas condition C-1). It is
   **groom-ready** (Iris spec v1.2, Atlas-gated 2026-06-05).
2. **Bug cleanup (2 open issues)** — the `sync_now.py` import break (found during
   the V0.29.1 deploy) + the simulate duplicate-timestamp test failure.

**Fully BENCH-VALIDATABLE** — every acceptance gate is a boot/shutdown drill or a
unit/integration test. **No drive drills** (CIO waived drive requirements
2026-06-29). The Pi is on wall power.

## Authoritative design

- **F-103 spec (GROOM-READY v1.2):** `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` — §9 has 18 boot/shutdown + 5 synthetic acceptance criteria + 7 failure modes (the source for per-story validationCriteria). Story split per spec §M-1.
- **Atlas UI greenlight + conditions:** `offices/pm/inbox/2026-06-19-from-atlas-ui-line-greenlight-plus-alert-deltas.md` (C-1 F-103 first; Rule-10 DoD: state-server + emitters + token land with matching `specs/architecture.md` updates in-sprint).
- **Iris groom-ready note:** `offices/pm/inbox/2026-06-03-from-iris-f103-groom-ready.md` (the US-A..D split + the A-1/A-2/A-4/A-6/A-9 hooks).
- **Bug 1:** `offices/pm/issues/I-sync-now-py-import-broken-on-pi.md`.
- **Bug 2:** `offices/pm/issues/I-simulate-duplicate-timestamp-parameter-rows.md`.

Atlas owns the UI architecture gate; Iris owns the splash design. Story-level detail
(goal / DoD / validationCriteria / conditionalOutcomes) is authored into `backlog.json`
+ Story.md mirrors at `/groom-user-stories`.

## Stories (build order follows `deps`)

| Story | Feat | Size | What it does |
|-------|------|------|--------------|
| **US-393** | F-103 | M | **Boot splash** — chromium kiosk on the 3.5" display + `eclipse-boot-state.service` emitter [A-1] + `eclipse-states-http.service` localhost-IPC :9899 + token SSOT + `HEALTHY_YIELD`. The runtime foundation. |
| **US-394** | F-103 | M | **Shutdown splash** — `ShutdownSequencer` phase-emit hook [A-2] + sequencer docstring timing-invariant [A-6] + **Rule-10 `specs/architecture.md` §10.6 update in-sprint (Atlas BLOCKs otherwise)**. |
| **US-395** | F-103 | S | **Deploy integration** — fold the F-103 units into `deploy-pi.sh` (sync-if-changed) + `version.txt` + WARN-not-BLOCK on missing assets [A-9]. |
| **US-396** | F-103 | S | **Defects + install-time checks** — close spec defects D-1/D-2/D-3 + V-1/V-2 install-time checks (may fold into US-393/394 at dev discretion). |
| **US-397** | F-076 | S | **Fix `sync_now.py` import break** — normalize the Pi entry-point to the `pi.*`-on-`src/`-path convention so the manual sync CLI runs without a PYTHONPATH workaround. Batch-audit other Pi-side `scripts/*.py`. |
| **US-398** | F-006 | S | **Fix simulate duplicate `(timestamp, parameter)` rows** — rule between test-fidelity (sub-second poll rate vs second-granularity timestamp) vs real data-quality, then fix the right one. |

Build chain: **US-393 → US-394 → US-395 → US-396** (F-103 is sequential — the boot
runtime underpins shutdown, deploy, defects). **US-397, US-398 are independent.**

## Per-story detail (validation-criteria-upfront)

### US-393 — F-103 boot splash (Iris US-A)
- **Goal:** As the Pi at boot, I want a branded boot splash on the 3.5" display backed by a chromium kiosk + a localhost state server, so the operator sees boot progress instead of a console/blank screen.
- **DoD:** chromium kiosk launches on boot rendering the splash; new `eclipse-boot-state.service` emits boot phases; new `eclipse-states-http.service` serves state on `localhost:9899` with token auth (token SSOT, one source); splash reflects the eclipse-obd 3-tier health (T1/T2=degraded, T3 engine-off=informational per Spool S-1/S-2) + `HEALTHY_YIELD`; retry-once on transient display/IPC failure. **Rule-10:** the state-server + emitters land with matching `specs/architecture.md` + `specs/UI/` updates in-sprint.
- **ValidationCriteria (bench/boot drill):**
  - reboot the Pi → splash renders on the 3.5" display within the spec's boot-grace window → splash visible (not console/blank)
  - `curl -H <token> localhost:9899/...` → returns the current boot state JSON
  - feed a synthetic boot-phase sequence → splash transitions through the phases (spec §9 synthetic criteria)
- **ConditionalOutcomes:** if HDMI/display isn't ready at boot, retry-once then degrade gracefully (no crash, no boot stall).

### US-394 — F-103 shutdown splash (Iris US-B)
- **Goal:** As the Pi during shutdown, I want a shutdown splash so the operator sees the staged shutdown instead of a frozen/blank screen.
- **DoD:** `ShutdownSequencer` emits phase events [A-2] the splash renders; shutdown splash shows the staged shutdown; sequencer docstring documents the timing invariant [A-6]; **`specs/architecture.md` §10.6 updated in-sprint** (load-bearing ShutdownSequencer change — Atlas design-gate DoD; BLOCKs if the hook ships without the spec update, M-1a).
- **ValidationCriteria (bench/shutdown drill):**
  - trigger a shutdown → shutdown splash renders + transitions through the shutdown stages
  - inspect `specs/architecture.md` §10.6 → documents the phase-emit hook + timing invariant
- **ConditionalOutcomes:** ShutdownSequencer IS load-bearing → the §10.6 update is mandatory in-sprint (not a follow-up).

### US-395 — F-103 deploy integration (Iris US-C)
- **Goal:** As the deploy path, I want F-103's units folded into `deploy-pi.sh` so the splash ships with every Pi deploy.
- **DoD:** `deploy-pi.sh` installs + enables `eclipse-boot-state.service` + `eclipse-states-http.service` (sync-if-changed, mirroring the existing unit-install steps); `version.txt` written; deploy **WARNs (not BLOCKs)** if splash assets are missing [A-9].
- **ValidationCriteria (bench):**
  - run `deploy-pi.sh` → the two F-103 units install + enable; re-run → no-op (sync-if-changed)
  - remove a splash asset + deploy → WARN emitted, deploy continues (not BLOCK)

### US-396 — F-103 defects + install-time checks (Iris US-D)
- **Goal:** As the F-103 surface, I want the spec's known defects closed + the install-time checks passing.
- **DoD:** spec defects D-1/D-2/D-3 resolved; V-1/V-2 install-time checks pass. May fold into US-393/394 at dev discretion (zero information loss).
- **ValidationCriteria (bench):** the D-1/D-2/D-3 repros no longer reproduce; V-1/V-2 install-time checks pass on a clean deploy.

### US-397 — fix `sync_now.py` import break (bug)
- **Goal:** As the operator, I want `python scripts/sync_now.py` to run on the Pi so I can trigger a manual sync without a PYTHONPATH workaround.
- **Root cause:** `sync_now.py` inserts the repo ROOT on `sys.path` + imports `src.pi.*`, but `src/pi/obdii/__init__.py:26` uses bare `from pi.display import ...` (the `pi.*`-on-`src/`-path convention the services run under) → `ModuleNotFoundError: No module named 'pi'`.
- **DoD:** `sync_now.py` follows the project Pi-tier convention ([[feedback-path-convention-no-src-prefix]]): put `src/` on `sys.path` + import `pi.sync` / `pi.data` (matching the services), NOT ROOT + `src.pi.*`. It imports + runs on the Pi with no PYTHONPATH override. **Batch-audit** other Pi-side `scripts/*.py` entry points for the same ROOT-insert + `src.pi.*` pattern; fix the cluster (Rule 5 batch).
- **ValidationCriteria (bench):**
  - on the Pi, `python scripts/sync_now.py --dry-run` → runs, no `ModuleNotFoundError`
  - an import/smoke test covers the `sync_now.py` (and any sibling) entry-point import under the service convention
- **ConditionalOutcomes:** if 3+ scripts share the bug, fix all in this one story (batch); if a script genuinely needs the ROOT/`src.pi.*` convention (server-side), leave + document.

### US-398 — fix simulate duplicate `(timestamp, parameter)` rows (bug)
- **Goal:** As the simulate-mode test suite, I want `test_noDuplicateTimestampParameterCombinations` to pass deterministically, with the underlying data-quality question resolved.
- **Investigation + fix (NOT investigation-only):** rule between (a) **test-fidelity** — the "no two rows share a (second-timestamp, parameter)" invariant is false at sub-second poll rates (`realtime_data.timestamp` is second-granularity ISO); the assertion should key on a higher-resolution timestamp or `id`; vs (b) **real data-quality** — if production also writes sub-second-duplicate rows, second-bucketed analytics could double-count → needs a finer timestamp or a uniqueness guard. Then **implement the corresponding fix**.
- **DoD:** the test passes deterministically (machine-speed-independent); the ruling (a vs b) + the fix are documented; if (b), the realtime_data write path / analytics is corrected (NOT just the test).
- **ValidationCriteria (bench):**
  - run `pytest tests/test_simulate_db_validation.py::...::test_noDuplicateTimestampParameterCombinations -q` → passes (and passes on a fast box, where it currently fails with 185 dups)
  - if ruling=(b): a query/test confirms production `realtime_data` no longer double-counts in second-bucketed analytics

## Validation (Argus) — BENCH ONLY

Every gate is a **boot/shutdown drill (on the Pi, wall power) or a unit/integration
test**. **No drive drills** (CIO waived drive requirements 2026-06-29). The frozen
`validation.bigDefinitionOfDone` aggregates the per-story validationCriteria above.
F-103's "IRL" acceptance from the spec §9 is boot/shutdown observation, not driving.

## Non-Goals (out of scope)

- **No carousel (F-092/F-097) or DTC viewer (F-111)** — those need Atlas's design-gate signoff (load-bearing Mode-04 write path); routed to Atlas in parallel; they are the **next** sprint once he signs. F-103 here is the prerequisite runtime.
- **No drive drills / no IRL drive validation** (CIO-waived).
- **No re-fix of the stale `.10` baseURL test** — already RESOLVED in US-392 (V0.29.1, drift-proofed via `serverHost:serverPort`).
- **No DTC / Mode-04 / vehicle-write paths** (deferred to the DTC-viewer sprint).

## Sequencing + open items

- Forks from `dev`; continues the **V0.29 chain as V0.29.2** (CIO 2026-06-29: stack on the chain, defer dev→main). `main` stays `V0.28.2`.
- **Route to Atlas in parallel:** request his design-gate signoff on the carousel (F-092/F-097) + DTC viewer (F-111) so they can groom as the next sprint (Sprint 49). Also owed at V0.29.1 validation: Atlas US-388 Rule-10 + US-367 FLAG-1 blessing.
- **Open question:** F-103 boot/shutdown rendering needs the 3.5" display attached + the Pi reachable for the bench drills — confirm the display is wired for Argus's acceptance pass.

## Next steps (PM)
1. `/groom-user-stories` → author US-393..398 into `backlog.json` + Story.md mirrors (counter 393→399).
2. Route F-103 to Atlas for his nod (spec already gated) + request carousel/DTC design-gate signoffs.
3. `prd_to_sprint.py` freeze → `sprint_lint` + `/resize-sprint` → Atlas Rule-13 → branch `sprint/sprint48-V0.29.2` + dispatch.
