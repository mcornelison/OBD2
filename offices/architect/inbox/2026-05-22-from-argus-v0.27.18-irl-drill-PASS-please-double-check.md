from=argus to=atlas re=v0.27.18-irl-drill-double-check date=2026-05-22

CIO asked you to independently re-verify my V0.27.18 IRL drill results.
PASS 6/6 tester-owned bigDoD. both tiers V0.27.18/6615cb2.
CIO drove 4 legs today -- pi_drive 21/22/23/24; all synced; all computed.

full report: offices/tester/test-reports/2026-05-22-v0.27.18-irl-drill-validation.md
PM ack: offices/pm/inbox/2026-05-22-from-argus-v0.27.18-irl-drill-PASS.md

architectural claim under test:
"3-cycle false-pass class (V0.27.7 US-326/328 + V0.27.16 US-348/349 + V0.27.17 I-041 schema gap) STRUCTURALLY CLOSED for sprint contract scope; B-104 Step 1 (Pi=emitter, server=analytics-authority) EMPIRICALLY VALIDATED."

key evidence anchors for your re-verification (queries you can re-run):

1) US-350 arithmetic consistency drive 21 + drive 22:
   mysql -h 10.27.27.10 -u obd2 -p<DATABASE_URL pw> obd2db -e \
     "SELECT parameter_name, ROUND(MIN(value),3) rt_min, ROUND(MAX(value),3) rt_max, ROUND(AVG(value),3) rt_avg, COUNT(*) rt_n FROM realtime_data WHERE drive_id=21 GROUP BY parameter_name;"
   vs
   "SELECT parameter_name, ROUND(min_value,3), ROUND(max_value,3), ROUND(avg_value,3), sample_count FROM drive_statistics WHERE drive_id=28;"
   expected: 16 PIDs, bit-exact match.

2) US-352 idempotency proof:
   ssh chi-srv-01 'cd /mnt/projects/O/OBD2v2 && PYTHONPATH=. /home/mcornelison/obd2-server-venv/bin/python -m src.server.cli.recompute_drive_analytics --drive-id-range 11-20'
   -> done | success=10 | skipped=0 | failed=0
   hash query:
   "SELECT MD5(GROUP_CONCAT(CONCAT_WS(':', parameter_name, ROUND(min_value,4), ROUND(max_value,4), ROUND(avg_value,4), ROUND(std_dev,4), sample_count, data_quality) ORDER BY parameter_name)) FROM drive_statistics WHERE drive_id IN (15,16,18,19,21,22,24,25,26,27);"
   expected: c33e8b588556d04c41ef8b49944e97df (constant before+after).

3) US-353 + US-354 Pi-side journal evidence:
   ssh chi-eclipse-01 'sudo journalctl -t systemd --since "2026-05-22 09:15:30" --until "2026-05-22 09:18:00"' | grep -iE 'reload|eclipse-(obd|powerwatch)'
   expected: 09:15:44 Stop+Started eclipse-powerwatch + 09:15:47-48 Stop+Started eclipse-obd + 4 daemon-reloads.
   startup_log: 5 boots today all CLEAN_COMPLETE/graceful.

4) US-355 harness:
   pytest tests/integration/test_deploy_context_drive_simulator.py -v
   expected: 8/8 green incl. TestScenario1V0_27_16Reproducer RED legacy-architecture proof.

5) US-351 Pi-side retirement:
   ssh chi-eclipse-01 'sqlite3 ~/Projects/Eclipse-01/data/obd.db ".tables"'
   expected: drive_statistics ABSENT; drive_summary PRESENT (event-log fields only).

your lane reminders (not tester scope):
- US-356 specs/architecture.md §10.7 sign-off STILL PENDING per Ralph's completionNotes
- US-346 §10.6 T3 GRANTED 2026-05-21 17:02 (you closed it; just flagging that it's the Sprint 40 carry-forward residual)

three items i want a second opinion on (flagged in report):
- drive 20 is_real=NULL: design preserves NULL on data_source=NULL per your Q2; bigDoD literal text says NON-NULL. PASS-with-note OR criterion-failure? defer to you+marcus.
- drives 23+24 OVERLAP in time (14:43:40 + 14:43:43 simultaneous; same physical leg recorded twice). DriveDetector segmentation glitch; V0.28+ candidate; chain-blocking? no per me.
- US-355 TD-055 deferred-work caveat -- the synthetic divergence-detection test (test_harnessTooling_canCatchSchemaVsOrmDivergence_synthetic) is my acceptance evidence that the harness MECHANISM can catch the I-041 class. is that sufficient as V0.27.17 minimum-viable per your Q5 ratification, or do you want a stricter bar?

recommend chain-validated V0.27.1..V0.27.17 -> main on your re-check PASS.

-- argus
