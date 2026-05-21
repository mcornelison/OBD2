From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Bench Check A (GPIO6 power-source line) — **GATE: PASS.**

evidence (CIO bench, corrected dependency-free pinctrl test):
- `pinctrl get 6` watch across 3 physical power cycles: hi×5 -> lo×4 -> hi×5 -> lo×7 -> hi×6 -> lo×4. Clean, REPEATED, BIDIRECTIONAL toggle correlated with adapter unplug/replug.
- CIO confirmed external power CONNECTED at capture start (first hi block).

verdict: BCM GPIO6 IS the X1209 power-loss line on THIS physical unit. Polarity = **HIGH = power present** (matches Geekworm/Suptronics vendor docs).

config CONFIRMED (no change): `pi.powerWatch.pldGpioPin=6`, `pi.powerWatch.pldPowerPresentHigh=true` are CORRECT as shipped. Do NOT change them. The PldSensor arm-self-check polarity assumption is empirically validated.

impact:
- Task 5 trigger now has empirical hardware backing. The SSOT GPIO6 ground-truth (PowerSourceProvider over PldSensor) is sound on this unit. The original "GPIO6 unverified on this unit" risk (spec §8.1) is CLOSED for Check A.
- This validates the TRIGGER only. NOT the wake loop. Check B (POWER_OFF_ON_HALT=1 unattended-wake) is still pending its proof. Chain stays BLOCKED until the full 5-cycle IRL acceptance.

unchanged: Task-1 GATE-PASS stands; the checklist-defect correction note (replace Check A with the dependency-free form + the deploy-state lesson finding) is still owed by you and re-routes to the architect inbox when done. T2-T4/T6-T9 clearance stands.
ack.
