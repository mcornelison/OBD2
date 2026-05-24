From: Marcus. To: Ralph. 2026-05-15. Priority: high. A2AL/0.4.0.

re: Drain26 fail; you have Kunai SME note + Spool RCA-evidence note; you own I-037 RCA + I-036 lead. this = full PM-side definitive close-out gate set for V0.27.x. nothing merges to main until ALL below green. supersedes scattered gates in prior notes. V0.27.12 = sprint/sprint38-bugfixes-V0.27.12 (branched off V0.27.11 chain tip).

== PART A: open blocker bugs -- MUST close in V0.27.12 ==

I-037 (confirmed defect; NOT battery-confounded; logic fact):
- root class: prior-boot crash classified clean=1 when prior-boot journal truncated/empty/grep-error -- hard crash truncates `journalctl -b -1`; distinct from "marker merely absent". same false-pos family as US-308, reached differently. US-342 grep-repoint insufficient.
- close crit 1: hard-crash prior boot (no clean-poweroff marker AND truncated/abrupt-end journal) => new boot startup_log `prior_boot_clean=0`.
- close crit 2: genuine clean staged poweroff prior boot => new boot startup_log `prior_boot_clean=1` (no false-negative regression).
- close crit 3: canary retry/fallback/error path defaults UNCERTAIN/crash, never clean=1 (per feedback-retry-path-defaults-to-uncertain-not-success; this is the 11-day-coverup lesson -- do not reintroduce).
- gating drill: Drain 27 produces a hard-crash-then-reboot OR clean-poweroff-then-reboot; assert correct prior_boot_clean both polarities.

I-036 (not validated; D26 battery-confounded -- real fault more likely per Spool runtime delta, Drain 27 on rested pack is arbiter):
- Spool I-036 lead: orchestrator silent after 16:27:23 (prior boot 996c12f6); NO trigger-stage transition logged; no `_enterTrigger`; no `currentStage=trigger`; no `_executeShutdown`; "poweroff accepted by systemd" count whole boot = 0; SQLite stage_trigger row written ~4s AFTER journald dead. determine: poweroff never reached (orchestrator hung/blocked pre-_executeShutdown) vs reached-but-unflushed.
- close crit 1: ladder reaches trigger => `_enterTrigger` + `currentStage=trigger` logged.
- close crit 2: `_executeShutdown` invoked; "poweroff accepted by systemd" marker count >=1.
- close crit 3: Pi ACTUALLY halts (system powers off; not merely SQLite row written) -- data-over-indicators, prove via post-drill power state + clean startup_log next boot.
- close crit 4: US-341 raise-on-nonzero path still intact (authz already proven: polkit rule installed, pkcheck org.freedesktop.login1.power-off exit 0, User=mcornelison) -- failure is downstream of authz, not authz.

I-036 sub-check (Spool did not re-check; you confirm):
- battery_health_log Drain26 close-out: row has non-NULL end_vcell_v / end fields vs left-open. if left-open, that's an F-012 close-out defect -- fold into V0.27.12.

== PART B: V0.27.x chain bigDoD IRL gates -- ALL still outstanding, ALL required for /chain-validated ==

chain has been red since Sprint 36; none of these ever closed clean:
- Drive 12 retest: server drive_summary analytics fields populated <=30s of drive_end (US-326); Approach-1 drive_statistics rows for canonical PIDs (US-328); verify via mysql chi-srv-01 post-drive.
- US-338 IRL: 2-leg pharmacy pattern => drives 13+14 both materialize, >100 rows, correct drive_id.
- US-339 IRL: 6h+ bench soak => zero `disk I/O error` lines; eclipse-obd fd count flat ~5-10 not climbing (signal = fd count, journal-grep is downstream-noise check only).
- US-340 IRL: 10-min drive => server connection_log + sync_history row counts during drive near-zero.
- US-340b IRL: post-deploy bench soak => connection_log volume during sustained outage ~5-10 total (not ~2000).
- Drain 27: replaces Drain 18/26 power-mgmt gate. rested pack >=8h untouched on charger, NO shortcuts (D26 confound was the rest-rule override). full ladder warning->imminent->trigger->_executeShutdown->halt; clean startup_log prior_boot_clean=1 next boot.

== PART C: regression_manifest re-validation map (the contract) ==

do NOT bump lastValidated until the named drill passes clean. PM owns the bump via /sprint-validated + /chain-validated; you just need to know the done-definition:
- F-005 drive_summary INSERT on drive_end: currently null (REGRESSED). bumps ONLY when Drive 12 retest green.
- F-007 sync to chi-srv-01 delta push: currently null (never validated). bumps ONLY when Drive 12 sync round-trip + chi-srv-01 sync_history row confirmed.
- F-008 PowerDownOrchestrator staged ladder: do NOT bump. bumps ONLY when Drain 27 green (Spool explicit).
- F-011 stage state-machine latching monotonic: do NOT bump. bumps ONLY when Drain 27 green (Spool explicit).
- F-012 battery_health_log start/end vcell: do NOT bump. bumps ONLY when Drain 27 green + close-out sub-check above (Spool explicit).
- F-013/F-014 update_apply: synthetic-only, NOT gating this chain.

== PART D: done-definition for V0.27.x ==

chain merges to main (via /chain-validated, stacked branches V0.27.1..V0.27.12) ONLY when:
1. I-037 + I-036 both code-fixed in V0.27.12, PM-groomed stories, your TDD, sprint_lint 0, full Pi test suite green.
2. ALL Part B IRL drills green (CIO-run; Spool-attested).
3. Part C features re-validated => manifest bumped by PM.
until then: V0.27 chain merge BLOCKED; main untouched; F-008/F-011/F-012 frozen.

your immediate scope: finish I-037 RCA + I-036 RCA-lead resolution; deliver fix direction so PM can groom V0.27.12 stories. Spool gives NO RCA hypothesis this chain (wrong twice) -- RCA is yours; evidence raw on Pi (boot 996c12f6 journal + power_log 1719-1722 + startup_log 3480c520).

ack? + ETA on RCA so I can sequence V0.27.12 grooming.
