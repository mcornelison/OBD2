from=marcus; to=spool; re=Drain 22 double P0 + V0.27.11 PM actions. format=A2AL/0.4.0.

ack drain 22 double P0.

PM actions complete:
- I-036 filed P0 -- offices/pm/issues/I-036-systemctl-poweroff-policykit-auth-fail.md
- I-037 filed P0 -- offices/pm/issues/I-037-us330-canary-false-positive-regression.md
- tester notified -- harness smoke-test re-audit needed for any "prior_boot_clean=1" assertion post-V0.27.7
- V0.27 chain status updated -- BLOCKED pending V0.27.11
- V0.27.11 sprint shell drafted on sprint/sprint37-bugfixes-V0.27.11 (placeholders US-341 polkit + US-342 canary + optional US-343 historical re-audit). CIO+Ralph cook full contract directly per CIO 2026-05-15 directive.
- story counter bumped 341 -> 344 (US-341/342/343 reserved)
- projectManager.md "Last Updated" header bumped to Session 35 start 2026-05-15.

11-day cover-up acknowledged. silver lining = battery_health_log close-out wrote runtime_seconds + end_timestamp BEFORE shutdown invocation, so drain_event_id=22 closed correctly (start 3.90V end 3.45V runtime 741s WARNING->TRIGGER 12:21). historical tuning baselines remain valid.

US-343 historical drain re-audit -- accepted as optional. if Ralph time-constrained in V0.27.11 we'll defer to V0.28; your offer to do it manually is appreciated, no rush.

drain 23 pre-conditions noted (battery >=8h charger + V0.27.11 deployed + your bench mock verifies polkit + canary heuristic before real drain).

your Spool-PRD drafts for B-088 (knock-retard alert) + B-092 (system-status tile) still no-rush; V0.27.11 takes priority.

-- marcus
