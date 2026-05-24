---
name: feedback-i040-discipline-insufficient-for-writer-bug-class
description: The "real-drive round-trip + DB read-back" gate Marcus tightened (I-040) did NOT catch a third recurrence of the writer false-pass class in V0.27.16. Synthetic seam mocks pass; integrated path fails. Test surface needs a deploy-context runner, not stronger acceptance criteria. Learned 2026-05-21.
metadata:
  type: feedback
---

The "I-040 discipline" Marcus imposed on Sprint 40 (US-348 + US-349 acceptance: *"synthetic-seam-mock passes do NOT count; real-drive round-trip + DB read-back is the gate"*) did NOT prevent recurrence of the same writer false-pass that V0.27.7's US-326 + US-328 had. V0.27.16 was the third cycle of this exact bug class.

**Why:**
Marcus's discipline is a stronger ACCEPTANCE bar. The bug is in TEST AUTHORING — Ralph's TDD writes a unit test that mocks the seam between DriveDetector and the recorder, asserts `recorder.write()` is called once with expected args. The test passes. The integrated runtime never fires `recorder.write()` because the actual DriveDetector signal that's supposed to trigger it never materializes in the deploy-context (e.g., drive terminated by sequencer poweroff before engine-off OBD signal reaches the detector). The acceptance bar can be "real DB read-back", but if NOTHING in the deploy IRL exercise actually fires the writer, the bar passes trivially (writer not present in disk = nothing to read back) or fails clearly (writer wired but no rows). Either way the bug stays hidden until IRL drill — which is what just happened, three sprints in a row.

**Pattern:**
- US-326 (V0.27.7) — synth tests passed, real path didn't fire. Failed at IRL drill.
- US-328 (V0.27.7) — synth tests passed, real path didn't fire. Failed at IRL drill.
- US-331 (V0.27.8) — synth tests passed, deploy-context (MSYS path-mangle) didn't catch. Failed at IRL drill. Redo US-337 V0.27.9.
- US-348 (V0.27.16) — explicit redo of US-326 under I-040 discipline. Same pattern. Failed at IRL drill.
- US-349 (V0.27.16) — explicit redo of US-328 under I-040 discipline. Same pattern. Failed at IRL drill.

**How to apply (Tester recommendations to PM/Atlas/Ralph for Sprint 41+):**
- For writer-class stories: require a **deploy-context test** that exercises the integrated orchestrator + DriveDetector + recorder path against a real DB, not synthetic mocks. The test must drive the **same deploy artifact** the IRL Pi runs.
- For drive-end specifically: the test must cover BOTH paths — drive ended by OBD engine-off telemetry AND drive ended by sequencer poweroff (no engine-off signal received before shutdown). The second path is the failure mode US-349 hit.
- For server-side analytics writers: the test must verify the trigger that causes server to compute fields. If the trigger relies on a Pi-sent "drive end" marker, validate that the Pi sends one, AND that the server processes it.
- I should NOT silently re-validate writer-class stories as "PASS" just because the writer's INIT log line appears. The log line means the wiring is loaded; it does not mean the wiring fires. Always check the data layer for actual writer output.

**My standing rule** (codifying for future drills): for any story that says "X writes Y to table Z when condition C", my acceptance evidence MUST include:
- An assertion that condition C was triggered IRL (e.g., drive ended for real)
- A SELECT against table Z that returns rows attributable to that specific event
- NOT just "writer is wired" or "writer init logged" — wiring is necessary but not sufficient

Related: [[feedback-tester-validate-deploy-fixes-irl-not-just-code]]
