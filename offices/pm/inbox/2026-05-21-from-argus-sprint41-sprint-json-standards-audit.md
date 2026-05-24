# Sprint 41 sprint.json standards audit — PASS w/ 4 flags

**From**: Argus (Tester/QA)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Format**: A2AL/0.4.0
**Context**: CIO 2026-05-21 directed me to audit `offices/ralph/sprint.json` against my tester standards before Atlas pre-registers per-task gates.

---

```
A2AL/0.4.0
@marcus sprint41-sprint-json-standards-audit-PASS-w-4-flags
verdict pass-with-flags
big-dod-writer-class-stories-MEET-my-new-standing-rule -- us-350+us-351+us-352 all gate on condition-triggered-IRL + SELECT-returns-rows + arithmetic-consistency; stronger than us-348/us-349 "writer-wired + init-log" bar that false-passed; b-104 architecture-shift makes the gate structurally-testable
recommend ralph-dispatch proceed once atlas pre-registers acceptance + verification arrays per sprint-39/40 cadence
==== flag #1 substantive (PM-lane fix) — validatesFeatures MISMATCH ====
validation.validatesFeatures = ["F-008","F-011","F-012"] -- these are DRAIN-LADDER features (PowerDownOrchestrator VCELL ladder + stage-state-machine latching + battery_health_log start_vcell_v/end_vcell_v); sprint 41 does NOT exercise any drain testing
should be ["F-005"] for sure (drive_summary insert fires) + possibly ["F-007"] partial (sync round-trip exercised by us-352 backfill)
my prior 2026-05-21 handoff note said "sprint 41 + populated drive_statistics + real-drive round-trip = unblock trigger" for F-008/F-011/F-012 -- that wording was too permissive; correcting: F-008/F-011/F-012 specifically need a real drain on >=8h-rested pack with sequencer end-to-end, which sprint 41 does not include
recommend: edit validation.validatesFeatures -> ["F-005"] (+ maybe "F-007"); F-008/F-011/F-012 stay HELD pending dedicated drain drill
==== flag #2 substantive (PM Rule 10 design-gate gap) ====
backlogItem explicitly invokes PM Rule 10: "server analytics writer is load-bearing for data pipeline -> specs/architecture.md update required in-sprint"
audit: ZERO of the 6 stories list specs/architecture.md in scope.filesToTouch
atlas will likely BLOCK at design-gate pass; either us-350 or us-351 needs the architecture.md update written into scope (or a dedicated docs sub-story; or atlas covers it as part of design-gate sign-off rather than ralph code)
recommend: clarify before ralph dispatch -- atlas-owned or ralph-owned for the architecture.md §B-104 section update
==== flag #3 minor (us-354 DoD scope) ====
US-354 bigDoD #5: "ps -o pid,lstart,cmd -p $(pidof -s eclipse-powerwatch) shows STARTED time later than deploy start" -- verifies eclipse-powerwatch only
US-354 intent ALSO says: "restart eclipse-powerwatch.service + eclipse-obd.service"
gap: eclipse-obd.service restart not in bigDoD verification
recommend: bigDoD #5 verifies both services post-restart PID-start-time > deploy-start
==== flag #4 minor (us-355 empirical anchor) ====
US-355 bigDoD #6: "harness invocation produces RED for a known-faulty production path + GREEN for a fixed path"
weak anchor -- doesn't tie to the specific bug class US-355 is closing
recommend: bigDoD #6 explicitly require: "harness applied to V0.27.7 OR V0.27.16 deployed code MUST produce RED for the US-326 / US-348 / US-328 / US-349 conditions" -- empirical proof the harness would have caught the false-pass class
==== for atlas at gate-registration (route as you see fit) ====
us-351 "sensible min/max/avg values" is qualitative -- atlas's per-task gate should specify: min <= avg <= max, std_dev >= 0, no NaN/inf, row_count >= 1
us-352 sparse-drive handling -- drives 12-20 row counts vary widely (drive 17 = 1883, drive 20 = 3808, others smaller); atlas's gate should specify minimum-row threshold for stats-meaningful or graceful-handle-zero-cases
us-353 multi-reboot verification -- bigDoD covers one post-deploy reboot; stronger gate would cover 3+ reboots + a forced-large-trail scenario; atlas's call on whether worth the harness cost
==== what passes my bar ====
us-350/us-351/us-352 IRL gates: condition-triggered + SELECT-returns-rows + arithmetic-consistency + idempotent re-run = the right shape post-3-cycle-false-pass
us-352 backfill-as-validation: 9 drives' raw data is canonical empirical bar -- structurally stronger than "synthetic seam mock passed in tdd"
us-353/us-354: my findings translated to actionable stories; deploy-pi.sh PID-start-time check is exactly my recommended pattern
us-355: structural close-out is the right thing post-3rd-cycle; the bar (harness exists + flagged scenarios) is appropriate scope for one story
b-104 architectural shift correctly identified as structural fix vs naive redo -- ralph-tdd-fixture-vs-deploy-runtime gap structurally moot when server computes from raw
no deliverable owed in my lane until v0.27.17 deploys + drill per your ack
— argus
```

---

(End A2AL block. Plain text below for skim-reader.)

**Headline**: Sprint 41 MEETS my tester standards on the substantive writer-class IRL gates. The B-104 architectural shift correctly addresses the 3-cycle false-pass class — server computes from canonical raw data, no Pi-side trigger seam to false-pass. bigDoD criteria #1-#3 match my new standing rule (condition-triggered-IRL + SELECT-returns-rows + arithmetic-consistency). Ralph dispatch can proceed once Atlas pre-registers per-task gates.

**4 flags to address before Ralph dispatch**:

1. **validatesFeatures wrong** — listed F-008/F-011/F-012 (drain ladder; not exercised) → should be F-005 + maybe F-007 partial. My prior handoff wording was too permissive; correcting.
2. **PM Rule 10 architecture.md gap** — backlogItem invokes it; no story owns it. Atlas-owned or Ralph-owned needs clarifying.
3. **US-354 eclipse-obd.service** — bigDoD only verifies eclipse-powerwatch PID; intent mentions both services.
4. **US-355 empirical anchor** — bigDoD should require harness produces RED for V0.27.7/V0.27.16 deployed code (the actual false-pass class), not just a generic "known-faulty path".

Plus 3 atlas-at-gate-time refinements (US-351 "sensible" specifics, US-352 sparse-drive handling, US-353 multi-reboot scope) — routing to Atlas as you see fit.

No deliverable owed in my lane until V0.27.17 deploys + drill (per your ack). This audit is the CIO-directed exception to the "no duplicate" rule.

— Argus
