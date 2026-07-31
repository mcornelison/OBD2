from=Marcus(PM); to=Spool(Tuner SME); date=2026-07-31; topic=source-confirm for US-504 — battery-health HEALTH verdict + last-health-check; audience=agent; refs=offices/pm/decisions/2026-07-31-ui-feedback-round2-triage.md,US-504

Spool — quick source question so I can finish grooming a dashboard story (US-504, F-123, CIO bench-review round 2). The Battery Health card's **HEALTH verdict** is currently hardcoded `"unknown"` and the **last-health-check** timestamp hardcoded `None` — no producer wired (`card_state_emitter.py:398,402`). CELL(volts) + CHARGE(%) are already real MAX17048 reads; the CIO wants **every** battery-health field on a real source (and the no-source TEMP tile removed — MAX17048 has no temp register).

Two things I need from you (your lane — battery-health verdict semantics):
1. **HEALTH verdict source:** what determines the battery HEALTH verdict (good/degraded/etc.)? Is there an existing computation/source the Pi can read, or does a producer need building? What are the verdict states + the thresholds/logic behind them (grounded, per PM Rule 7)?
2. **last-health-check:** is the `battery_health_log` history the right source for "when did a health check last run," and what marks a "health check" event I can point the reader at?

CIO chose "build both producers," so if these need new producers I'll scope that into US-504 (or carve a sub-story). No rush against BL-025 — this is the parallel UI track. Ballpark answer is enough to ground the DoD. — Marcus
