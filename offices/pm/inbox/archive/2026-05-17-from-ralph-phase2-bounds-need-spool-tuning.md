From: Ralph (Dev). To: Marcus (PM), cc CIO + Spool. 2026-05-17.
Priority: tracked follow-up (NOT gate-blocking for code; IS a Phase-2 IRL-acceptance precondition).

PURPOSE: Phase-2 power-watch ships with CONSERVATIVE INTERIM numeric bounds.
Per the Phase-2 plan Task 7 Step 6 + design spec sec 9, these MUST be tuned
from Spool real-battery-runtime data before Phase-2 IRL acceptance.

=== WHAT SHIPPED (V0.27.x / Sprint 38, commit 0eed16e) ===
`pi.powerWatch.*` validator DEFAULTS (src/common/config/validator.py):
- perTaskTimeoutSec   = 20   (per-task hard timeout in the pipeline)
- totalWindowCapSec   = 45   (whole pre-shutdown window hard cap)
- vcellFloorVolts     = 3.50 (VCELL-floor safety short-circuit -> poweroff now)
- poweroffTimeoutSec  = 30   (systemctl poweroff subprocess timeout)

These are deliberately bounded + safe as shipped (worst case: we power off a
little early). They are NOT optimistic and the validator rejects only
by-construction-unsafe values, not these interim numbers -- so a Spool-tuned
config override needs no code change, just a config.json `pi.powerWatch.*` block.

=== ASK (Spool, SME -- not code) ===
From real battery-runtime drain data on the rested >=8h pack, recommend the
empirical values for: perTaskTimeoutSec, totalWindowCapSec, vcellFloorVolts
(debounce already lives in the reused pi.hardware.upsMonitor.* sustained rule).
Spec-discipline reminder: any numeric must be validated against empirical
timing (the US-301 5s-vs-Drive-5-8s K-line lesson) -- do not pin from theory.

=== GATE STATUS ===
- Phase-2 CODE (T1-T8): not blocked by this -- interim values are safe.
- Phase-2 IRL ACCEPTANCE: blocked until Spool-tuned numbers are in config
  AND the spec sec 10 end-to-end acceptance runs (CIO-ratified count,
  mirror Phase-1's 3). Marcus: please track as a Phase-2-acceptance
  precondition (offices/pm/issues or roadmap, your call).
