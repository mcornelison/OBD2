from=argus to=marcus re=v0.27.18-irl-drill date=2026-05-22

V0.27.18 IRL drill PASS 6/6 tester-owned bigDoD.
both tiers V0.27.18/6615cb2; chi-srv-01 + Pi Chi-Eclips-01 green.
CIO drove 4 legs today -- pi_drive 21/22/23/24; all synced; all computed.

US-350 PASS: drives 21-24 drive_summary non-NULL via on-demand recompute; arithmetic bit-exact vs realtime_data MIN/MAX/AVG/COUNT (16 PIDs spot-checked).
US-351 PASS: drive_statistics 16 rows/drive across all 14 drives 11-24; data_quality classification correct; Pi-side drive_statistics table ABSENT (retired).
US-352 PASS: deploy backfill 10/10 success; marker written per I-042 gate; idempotent re-run hash identical c33e8b58...e97df = zero diff.
US-353 PASS: 5 boots today all CLEAN_COMPLETE/graceful; zero maxTrailBytes trips; TI-008 first-reboot-artifact doesn't recur.
US-354 PASS: deploy journal 09:15:44 daemon-reload + Stop+Started eclipse-powerwatch; 09:15:47-48 Stop+Started eclipse-obd; 4 reloads observed; TI-007 closed.
US-355 PASS-with-note: pytest 8/8 green; RED legacy-writer test catches V0.27.16 false-pass class; TestHarnessIntegrity tripwires pin claims; TD-055 deferred-work caveat honestly documented; minimum-viable per Atlas Q5 ratified.

3-cycle false-pass class STRUCTURALLY CLOSED for sprint contract scope.

flags-non-blocking:
- drive 20 is_real=NULL (legacy data_source=NULL; design preserves NULL per Atlas Q2; bigDoD literal text says NON-NULL -- your+atlas disposition)
- drives 23+24 OVERLAP in time (14:43:40 + 14:43:43 simultaneous; DriveDetector segmentation glitch; not Sprint-41-introduced; V0.28+ DriveDetector hygiene)
- live trigger gap (compute fires overnight + on-demand only; new drives wait for batch; per CIO ratification of Atlas Q1; V0.28+ if HDMI dashboard wants near-real-time)
- TI-006 hardware_manager 'powerSource' KeyError unchanged (pre-existing journal noise)
- drive_summary.drive_id NULL on backfill rows (only source_id set; pre-existing legacy; V0.28 schema epic)

recommend:
1) sprint-validated Sprint 41 -- tester axis green; awaits Atlas US-356 §10.7 sign-off + US-346 already-PASSED 2026-05-21.
2) sprint-validated Sprint 40 -- unblocked on design-gate axis (US-346 PASS) + on US-348/349 false-pass axis (superseded by B-104 Step 1, empirically validated above).
3) chain-validated V0.27.1..V0.27.17 -> main -- tester signs off; CIO+PM drive.
4) regression_manifest bump F-005 + F-007 lastValidated=2026-05-22 (drive 21+22+23+24 evidence). F-008/F-011/F-012 STAY HELD (no drain today).

full report: offices/tester/test-reports/2026-05-22-v0.27.18-irl-drill-validation.md

-- argus
