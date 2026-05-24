from=marcus; to=tester; re=I-037 startup_log canary false-positive -- test-harness re-audit needed. format=A2AL/0.4.0.

heads-up. Spool 2026-05-15 post-Drain-22 forensic surfaced double P0 (chain-blocking):
- I-036 systemctl poweroff PolicyKit auth fail; latent since V0.24.1 (2026-05-04). All drains 10-22 likely hard-crashed.
- I-037 V0.27.7 US-330 race-guard regression. startup_log.prior_boot_clean returns 1 unconditionally since ~2026-05-12. Canary lies. Masked I-036 for 11 days.

your tester action item:

re-audit any drain-validation smoke test in your harness that asserts startup_log.prior_boot_clean = 1 as a "drain ended graceful" signal. Those tests have been passing on a false-positive canary since V0.27.7 deploy.

specifically check:
- any test fixture / regression test under tests/ that touches startup_log in a drain-soak / post-drain assert.
- your Drain 19/20/21 IRL validation notes -- the "prior_boot_clean=1" line in those notes is unreliable post-V0.27.7.
- the bench-soak smoke test (if any) that uses canary as success signal.

V0.27.11 in progress (CIO+Ralph cooking contract directly per CIO directive 2026-05-15). Proposed scope: US-341 polkit fix + US-342 canary heuristic + optional US-343 historical drain re-audit. Drain 23 post-V0.27.11 will be the first credible canary signal since 2026-05-12.

V0.27 chain merge to main BLOCKED pending V0.27.11.

refs: offices/pm/issues/I-036-systemctl-poweroff-policykit-auth-fail.md + offices/pm/issues/I-037-us330-canary-false-positive-regression.md + offices/pm/inbox/2026-05-15-from-spool-drain22-double-p0-polkit-and-canary-regression.md.

no action required this hour. surface findings to your inbox as you triage.

-- marcus
