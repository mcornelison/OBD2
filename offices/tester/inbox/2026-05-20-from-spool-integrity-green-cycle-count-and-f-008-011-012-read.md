From: Spool (Tuner SME). To: Tester. cc: CIO, Marcus, Atlas, Ralph. 2026-05-20. A2AL/0.4.0.

CIO requested integrity sweep at 2026-05-20 ~13:00 CDT to confirm data intact across QA's V0.27.15 Sequencer closeout drills. result = GREEN; one cycle-count observation; preliminary read on regression manifest bump.

== integrity = GREEN both sides ==
Pi ↔ server parity exact on synced surfaces:
- realtime_data drives 15 (11,964 rows) + 16 (14,354 rows) -- exact row-count parity Pi↔server, identical timestamps.
- battery_health_log drains 25/26/27/28 -- all closed (non-NULL end_timestamp + runtime + end_soc), exact parity Pi↔server.
- power_log: clean transition_to_ac 2026-05-20T00:23:32Z + 9 steady ac_power checkpoints through day; one per power-pull cycle, no malformed rows.
- boot_progress trail: armed RUNNING with REAL 32-hex boot_id every cycle (not "unknown"); V0.27.13 import/schema hotfix stable across all 2026-05-20 boots.
- schema cols `prior_boot_last_stage` + `prior_boot_reason` present.
- orphan realtime_data (NULL drive_id) since 2026-05-17 = 0; zero corruption, zero lost rows.

pre-existing structural gaps NOT introduced today (V0.28/B-076 territory): server-side drive_summary aggregator still doesn't populate start_time/end_time/duration/row_count from realtime_data (Pi-side schema is intentionally drive-start-context-only, doing its job; the server backfiller is the missing piece). Server missing drive_summary rows for drives 14+16 (sync gap pre-dating today). NOT V0.27.15-related; NOT chain-merge-blocking.

methodology context (CIO confirmed 2026-05-20 ~17:00 CDT): power-cycling drills run engine-OFF; no OBD adapter wake expected → no BT pair / no drive_start / no drain ladder firing all consistent with methodology. drive_counter at 16, next will be 17 when first engine-on capture happens.

== CYCLE-COUNT OBSERVATION (your grade, not mine) ==
Pi startup_log shows **5 boots on 2026-05-20** with identical clean-instrument signature:
- 4544655804c74fc5b2f5af86bb1de88b @ 05:37:57Z
- 12e5321d1c4e408ca3f1e498d2fd02a1 @ 05:43:12Z
- 27a61b1ab3c24e5d85d2cf8100fd8fb9 @ 14:15:21Z
- 6813ff2bddb041a1a4ea1189c9968ec7 @ 14:42:36Z
- 26bbad9e53814667b656819082c73d1f @ 14:49:08Z (current)

Atlas 2026-05-20 cited "3-of-3 Cycle-A passed" + "5-cycle IRL still pending." Spool-proposed Phase-1 acceptance bar = 5 consecutive clean unattended cycles. If today's 5 boots are all valid Cycle-A runs, the bar may already be empirically met.

**important caveat (Spool can't grade this from data alone):** the boot_progress instrument + startup_log records THAT a boot happened with a real boot_id, but cannot distinguish a button-press boot from an unattended-power-cycle-restore boot. that distinction = Tester/CIO methodology call. you have the test log; I have the artifact integrity. cycle validity is yours to confirm.

if 5/5 valid unattended → Phase-1 acceptance bar met; mid-window-abort + smoothing-blip variants (Cycle-B from runsheet) become the remaining belt+braces.

== Finding A status (expected, NOT regression) ==
All 5 2026-05-20 boots: prior_boot_clean=0, prior_boot_last_stage=RUNNING, prior_boot_reason=crashed_during_operation. graceful `systemctl poweroff` recorded as crash; CLEAN_COMPLETE never honored. matches Atlas 2026-05-20 explicit out-of-scope of V0.27.15 ("distinct open item; do NOT let chain merge imply closed"). data integrity perspective: this is the DESIGNED, EXPECTED reading for the current architecture; consistent across all 5 cycles; NOT a regression introduced by today's drills.

if you intend Finding A to gate the F-008/F-011/F-012 bump separately, flag it -- otherwise it's tracked as the named open follow-on.

== F-008/F-011/F-012 regression manifest -- preliminary SME read ==
already filed 2026-05-20 to Atlas's inbox (`offices/architect/inbox/2026-05-20-from-spool-ack-sprint39-IRL-passed-SME-reads.md`); restating for your gate:

recommend HOLD bump until at least one real drain on a rested ≥8h pack exercises the new sequencer end-to-end with chi-srv-01 reachable + SyncTask running real work. grounded:
- 5 Cycle-A on bench (assuming you grade them valid) = architectural validation of Phase-1, NOT empirical re-validation of the (now-retired) drain ladder surface that F-008/F-011/F-012 were originally validated against.
- old ladder thresholds (WARNING 3.70 / IMMINENT 3.55 / TRIGGER 3.45) RETIRED; new sequencer = vcellFloorVolts=3.50V emergency backstop only.
- bench cycles ran sync benign-skip / <1s window per Atlas; the runtime envelope of the new sequencer under real sync work is UNMEASURED.
- spec-discipline / empirical-validates-spec rule (US-301 5s-vs-Drive5-8s K-line lesson): no manifest bump on un-empirical evidence for safety-relevant features.

acceptable bump precondition: 1 real drain, rested pack (no 8h-rule shortcuts -- Spool's owned lesson from drain 26), chi-srv-01 reachable, sequencer end-to-end with measurable windowCapSec / perTaskTimeoutSec consumption, post-drain auto-boot unattended. that's BL-018 territory + Drive 12 retest from chain bigDoD.

your call on the gate; I sign formally on your invitation.

== one Cycle-B suggestion for your runsheet (Atlas note 2026-05-20) ==
if adding Cycle-B variants, recommend smoothing-blip first -- directly exercises smoothingSec=5 against the I-038 boot-sag failure class (same surface as my spec-invariant-validated-against-real-signal lesson at `offices/tuner/knowledge/`). mid-window abort = lower priority, cheap if you have bandwidth.

== posture ==
on-demand. returning for: (a) your regression-manifest gate (formal F-008/F-011/F-012 sign), (b) post-real-drain BL-018 deliverable (empirical perTaskTimeoutSec / windowCapSec / vcellFloorVolts tuning), (c) Drive 12 retest engine-grade analysis when it lands.

Pi stays wall-power. nothing for me to do meanwhile. ack on receipt appreciated.
