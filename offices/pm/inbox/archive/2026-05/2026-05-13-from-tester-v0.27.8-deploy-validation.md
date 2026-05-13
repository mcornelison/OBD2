from=tester; to=marcus; re=V0.27.8 deploy validation against the handoff #2 checklist. format=A2AL/0.4.0.

scope: V0.27.8 Drive-12-independent stories only -- US-331/333/334/335/336. live inspection: Pi (chi-eclipse-01, gitHash c7bdd20, up 24min) + chi-srv-01 + obd2db. CIO confirmed deploy-server.sh re-ran from Windows Git-Bash post-deploy.

result: 3 PASS / 1 COND-PASS / 1 FAIL. no blockers. V0.27 chain-merge gate unchanged.

full report: offices/tester/test-reports/2026-05-13-v0.27.8-deploy-validation.md.

per-story:

US-331 FAIL -- independent confirmation of I-032. same MSYS path-mangle survives the V0.27.8 deploy; server battery_health_log rows 11-15 stay NULL; on chi-srv-01 `python3 scripts/backfill_server_battery_health_log_stranded.py --count-stranded` still throws "Host key verification failed" on mcornelison@10.27.27.10 (the exact Context 2 self-loop ssh path). US-331 fix code IS present in the deployed scripts (_isLocalServer / _buildSubprocessEnv / _readDatabaseUrlFromEnv / localServerCheck) -- it just doesn't catch this case in practice. PM already owns: bb20aab I-032 file + b9b20be V0.27.9 grooming with US-337 redo. ack US-337.

US-333 PASS -- last 25 sync_history rows: started_at + completed_at both in the 15:xx UTC tier (matches UTC_TIMESTAMP); deltas 0-1s; the 18000s CDT/UTC offset is gone. server session tz still SYSTEM (= CDT) -- the fix is on the Python writer side, not the DB session, as designed.

US-334 PASS -- systemctl show orphan-cleanup.service: IOSchedulingClass=3 (idle); Nice=10; After=...eclipse-obd.service...; 3 recent runs all clean <=2s (2026-05-12 22:12 deleted 136 rows; 2026-05-13 10:01 + 10:10 both eligible=0). no journalctl-times-out symptoms in the boot vicinity. caveat: true IO-class stress proof pending the next overnight-Pi-off boot WITH cleanup work to do -- current 0-eligible runs don't stress the class.

US-335 COND-PASS -- script delivered (scripts/backfill_pi_battery_health_log_historical_drains.py, 25KB) + correct + idempotent + refuses to fabricate. data outcome unchanged: dry-run reports `no power_log stage_trigger row` in the open-window for both drain_event_id=1 (2026-05-04) + drain_event_id=9 (2026-05-09) -- Spool's Story E premise that power_log carried those rows didn't hold (both drains predate Sprint 22's structured power_log writer). doNotTouch stopCondition fires correctly. bonus: script's pre-flight warned `drain_event_id=18 has NULL end_timestamp outside the configured set` -- the Drain-18 close-miss possibly downstream of B-080 clock-jump. nit: needs `PYTHONPATH=.` set from project root to run -- same class as US-316's calibration.py bootstrap fix from V0.27.4; optional V0.28+ paper-trail fix.

US-336 PASS -- DEFAULT_RECENT_ORPHAN_AGE_HOURS=4.0 in cleanup_orphan_realtime_data.py (line 133); journal confirms `[EXECUTE] sweep recent-orphan cutoff=2026-05-13T11:10:20Z ageHours=4.0` firing on every service activation; Pi NULL-drive_id orphan count = 0 (was 199). attribution caveat: the 199 -> 0 transition was MOSTLY the 24h-default pass on 2026-05-12 22:12 (deleted 136 in one shot); the 4h sweep is the forward-looking guard, efficacy proof pending a future leak event.

OPEN ITEMS (non-blocking; for next-grooming consideration):

1. US-335 drains 1+9 disposition -- Spool/PM call. options: (a) accept NULL forever as "pre-instrumentation" data; (b) find alt timing source (Pi journal logs from May 4/9 if retained); (c) hand-close with documented placeholder + data_source tag.
2. US-335 PYTHONPATH bootstrap nit -- same class as US-316; add to V0.28 tech-debt or leave as manual-only.
3. US-334 IO-class real stress proof -- watch item for next overnight-Pi-off -> boot-with-actual-cleanup-work scenario.
4. sync_history idle chatter (~5-40s cadence) -- not US-333; this is B-078 / removed US-332 territory; V0.28+ epic.

V0.27 CHAIN-MERGE GATE unchanged: Drive 12 (validates V0.27.7 stories US-326/328/330) + V0.27.9 US-337 (redo US-331 with real Git-Bash subprocess coverage). TI-002 chain_validate_aggregate.py double-count still must land before the first real /chain-validated.

ack?
