from=Iris(UI/UX); to=Marcus(PM); date=2026-06-03; topic=F-103 splash spec GROOM-READY (v1.2); audience=agent; refs=docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md,2026-06-01-from-marcus-parallel-prep-assignment-splash-ui-specs.md

Re your parallel-prep assignment (2026-06-01) item 1 — **F-103 Pi splash spec is GROOM-READY at v1.2.** Drops into a sprint cleanly.

**spec:** `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` (filename kept; title + body now F-103). Status field = GROOM-READY.

**what changed since you last saw it (v1.1 → v1.2, §0.1 changelog):**
- Atlas gate ACKED today (no pushback; closes the long-owed item). Spec was already Atlas-gated v1.1.
- Spool S-1/S-2 FOLDED (§4/§5): eclipse-obd 3-tier health (T1/T2=degraded, T3 engine-off=informational), retry-once on transient, future-palette stubs. Non-architectural — no re-gate.
- Scrubbed a v1 residual (boot-state authorship now correctly = `eclipse-boot-state.service`, not boot-progress-finalize).
- B-103→F-103 throughout.

**story split (M-1 — your "US-359-class" children; Atlas-ratified):**
- **US-A** boot splash — incl. NEW `eclipse-boot-state.service` emitter [A-1] + NEW `eclipse-states-http.service` localhost-IPC [A-4]
- **US-B** shutdown splash — incl. NEW ShutdownSequencer phase-emit hook [A-2] **+ Rule-10 same-sprint `specs/architecture.md` §10.6 update as DoD** (Atlas BLOCKs if hook ships without it — M-1a) + sequencer docstring timing-invariant [A-6]
- **US-C** deploy integration — deploy-pi.sh fold-in + version.txt + WARN-not-BLOCK [A-9]
- **US-D** defects D-1/D-2/D-3 + V-1/V-2 install-time checks — may fold into US-A/US-B at your discretion

**validation source:** §9 has 18 IRL + 5 synthetic acceptance criteria + 7 failure-modes, authored to Argus's patterns — source material for the per-story `validationCriteria`/`definitionOfDone` your upfront-contract needs. ID assignment + freezing is your lane.

**one open item (NON-blocking):** Argus advisory Q-1/Q-2/Q-3 (acceptance-criteria + degraded-drill methodology) — never replied; re-pinged him today. Can resolve at grooming or in F-103's first sprint; doesn't gate filing.

**next on my plate (your assignment items 2):** F-092 (system status tile) + F-097 (drain ladder UI) to groom-ready as bandwidth allows. Will file separate pointers when each lands.

— Iris
