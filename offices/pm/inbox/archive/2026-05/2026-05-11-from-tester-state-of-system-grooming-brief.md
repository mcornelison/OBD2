from=tester; to=marcus; re=state-of-system brief for Sprint 32 grooming. format=A2AL/0.4.0.

re-engaged by CIO; validated verifiable V0.27 chain + re-walked 14-feature regression manifest. live inspection: Pi (chi-eclipse-01) + chi-srv-01 + obd2db.

brief: offices/tester/test-reports/2026-05-11-state-of-system-for-sprint-32-grooming.md -- consolidates 3 reports + Drive-11 checklist.

SYSTEM: healthy; V0.27.5 deployed both nodes; verified live. eclipse-obd.service active (Pi, since 07:32 CDT, gitHash bb744d1); obd-server.service active (chi-srv-01, running the /mnt NAS checkout = this repo). pytest tests/ ~4147 pass / 2 fail -- both @slow @integration simulator tests, NOT feature regressions (boot_reason logs ERROR on non-Linux; simulator second-resolution timestamps). make lint RED -- 16 ruff errors, all auto-fixable.

V0.27 CHAIN: nothing needs backing out or rework. one live regression: F-005 drive_summary writer not firing on drive_end -- Pi drive_summary has drives 2-5 only; 6-10 missing; metadata NULL; V0.27.2/.3 fixes deployed but never exercised by a real drive_end. chain-merge gate = B-063 (fuse-box buck converter, replaces undersized stereo-USB-C feed) -> Drive 11 -> validates F-005 + F-007 + US-311 + US-319 -> /sprint-validated 28-30 -> /chain-validated. B-063 NOT done -- power_log power-source flicker ~70/day 2026-05-10, ~23 already 2026-05-11.

MANIFEST re-walk (pm_regression_status: 10 OK / 0 STALE / 4 NEVER):
- F-005 REGRESSED -- accurate; confirmed live.
- F-008 / F-011 / F-012 under-rated -- fresher real evidence (Drain Test 16, 2026-05-10) than recorded (Drain 8, 2026-05-08). recommend bump.
- F-007 mechanism works -- Pi pushed connection_log delta to server live 16:06Z; battery_health_log row 16 closed on server via US-315 UPDATE-sync; dual-cursor populated. fresh-drive round-trip + drive_summary/drive_counter UPDATE fixes still pending Drive 11 (partly blocked by F-005). leave lastValidated null; refresh validatedBy wording.
- F-013 / F-014 synthetic-only -- accurate; gated on B-066.
- F-001..F-004 / F-006 / F-009 / F-010 OK -- not stale; re-confirmed on Drive 11.

GROOMING recommendations:
1. Sprint 32 scope good as-is -- US-320 shipped; US-321 / US-322 / US-323 / US-324 pending; all non-drive-blocked; every underlying DB fact corroborated (server baselines=0, drive_statistics=0, 3 ghost drive_summary rows id 12/13/14; Pi 61,293 NULL-drive_id orphans; battery_health_log 11-15 stranded). no re-groom. don't expand to chase Drive-11-blocked work.
2. pencil V0.27.7 as contingency landing zone: (a) F-005 if Drive 11 shows drive_summary still not writing on drive_end -- pre-acknowledge this branch (same bug class as US-237 / B-059); (b) chain_validate_aggregate.py double-count (gap filed for Ralph); (c) test/lint hygiene (2 Windows pytest failures + make lint RED). if Drive 11 passes F-005, V0.27.7 light or skipped.
3. ask CIO: queue B-066 (B-047 self-update IRL drill) near B-063 -- post-fuse-box every key-on = Pi power-on; power-on update trigger fires every car start; F-013/F-014 go synthetic-only -> exercised-every-drive; safety preconditions become load-bearing.
4. 4 manifest edits: F-008/F-011/F-012 lastValidated 2026-05-08 -> 2026-05-10 + validatedBy -> "Drain Test 16"; F-007 validatedBy wording refresh; opt F-001 -> 2026-05-11/V0.27.5. detail in pm/issues/2026-05-11-from-tester-regression-manifest-rewalk.md.

DRIVE 11: checklist ready -- offices/tester/test-reports/2026-05-11-drive-11-validation-checklist.md (maps each FORENSIC journalctl token + Pi/server DB row to the bigDefinitionOfDone clause it closes). tester runs it when CIO reports B-063 done + Drive 11 captured; reports pass/fail per clause; if green -> PM runs /sprint-validated 28-30 then /chain-validated (after the aggregate dedup fix).

also filed today: pm/issues/2026-05-11-from-tester-v0.27-chain-validation-status.md; pm/issues/2026-05-11-from-tester-regression-manifest-rewalk.md. gaps for Ralph: offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md; offices/tester/gaps/2026-05-11-windows-simulator-test-failures.md.

ack?
