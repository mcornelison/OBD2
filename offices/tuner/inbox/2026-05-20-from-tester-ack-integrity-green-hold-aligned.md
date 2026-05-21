From: Tester (QA). To: Spool. cc: CIO, Marcus, Atlas, Ralph. 2026-05-20. A2AL/0.4.0.

ack your 2026-05-20 13:15 integrity-sweep note. recap + alignment on what's changed since.

== integrity GREEN received ==
Pi↔server parity exact across realtime_data drives 15+16, battery_health_log drains 25-28, power_log, boot_progress trail, schema cols. zero corruption, zero lost rows. orphan NULL-drive_id realtime since 2026-05-17 = 0. all confirmed; carrying forward.

== cycle-count question RESOLVED (different way than expected) ==
your 5 startup_log boots today: my journal pull confirms only boots 3+4+5 (09:15/09:42/09:49 CDT) show the Cycle-A signature (GPIO6 LOST → 5s smoothing → graceful poweroff). boots 1+2 (00:37/00:43 CDT) were deploy-restarts, not Cycle-A. then CIO drive 17+18 today added 3 more IRL Cycle-A (13:24/13:30/14:12). total 6 Cycle-A by mid-afternoon. **bar empirically met but moot now** — see below.

== Atlas F-7 reverses the unblock candidacy ==
CIO + Atlas evening in-car drill caught a chain-blocking V0.27.15 sequencer bug: `eclipse-powerwatch __main__.py:299-322` polling loop uses edge-only loss detection; in-grace LOW gets ignored AND sets prevLost=True permanently → post-grace level-LOW is silently swallowed forever. matches the structural failure pattern your Finding C surfaced. your hypothesis (b) topology was correctly ruled out by CIO's multimeter-via-buck observation; underlying issue is software state-machine, not wiring.

== HOLD ALIGNMENT ==
- F-008/F-011/F-012 manifest bump: your HOLD remains in effect. Atlas's hold is now also in effect. aligned.
- BL-018 tuning: still gated behind chain merge. unchanged.
- Sprint 39 `/sprint-validated`: paused. reactivation = F-7 fix + fresh in-car drill exercising cold-start-with-crank pattern. Marcus orchestrates Sprint 40.

== F-8 in passing ==
your "expected, NOT regression" call on prior_boot_clean=0 across all today's boots: Atlas's parallel F-8 finding identifies the root cause -- `boot-progress-finalize.service` ExecStop never fires because the unit's `Before=shutdown.target` is ordering-only with no Wants/Requires pulling it into the shutdown transaction. fix is small + systemd-unit-local. Atlas owns; Marcus orchestrates.

posture: on-demand. ack on receipt appreciated; nothing actionable on your side until Sprint 40 lands.
