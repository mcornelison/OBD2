from=Marcus(PM); to=Rex(Dev); date=2026-06-19; topic=DISPATCH Sprint 46 / V0.29.0 EDR bus Slice 1; audience=agent; urgency=medium; refs=F-110,E-006,A-14

DISPATCH: Sprint 46 / V0.29.0 is FROZEN + Atlas Rule-13 PASS. GO. (Supersedes the "await PM dispatch" on Atlas's 2026-06-18 plan pointer.)

CONTRACT: offices/ralph/sprint.json -- 6 stories US-380..385 (F-110 / E-006 "EDR bus Slice 1"). Frozen hash 17bc9d6f, 19 bigDoD clauses. Branch sprint/sprint46-V0.29.0 (already checked out).

DESIGN (authoritative -- read first):
- spec: docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md
- TDD plan (complete code, 9 tasks): docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md

BUILD ORDER (follow deps): US-380 (data types) -> US-381 (bus core) -> US-382 (STATE + integrity-gap) -> US-383 (PersistenceSubscriber, byte-identical golden master) -> US-384 (publish seam + pi.bus.enabled flag) -> US-385 (orchestrator wiring, ships-dark cutover).

KEY GUARDRAILS:
- Ships DARK: pi.bus.enabled defaults FALSE. Flag-off full fast suite MUST stay green (zero behavioral change on merge). That is the merge gate.
- US-383 golden master: REUSE ObdDataLogger.logReading() -- do NOT reimplement the realtime_data INSERT. Rows must be byte-identical to the inline path.
- Verify-before-impl (per plan, at each task): exact ObdDataLogger.__init__ sig; createRealtimeLoggerFromConfig sig (add/forward bus); orchestrator class/attr names in lifecycle.py; whether utcIsoNow/getCurrentDriveId are imported in realtime.py.

CONCURRENCY (handbook §13): US-384 adds `pi.bus.enabled` to config.json. Atlas added `pi.runtime.singleInstanceGuard` to config.json earlier today (d6d8b05) -- DIFFERENT key, no conflict, but RE-READ config.json immediately before you edit it (shared checkout races). Commit your work office-scoped to this sprint branch; do NOT push/merge (PM integrates at /sprint-deploy-pm).

VALIDATION (Argus axis, post-build): byte-identical realtime_data golden master + flag-off full-suite green. Post-merge Pi flag-flip is a SEPARATE deploy gate (PM/CIO), not your concern this sprint.

-- Marcus
