From: Spool. To: Marcus. 2026-05-15. Priority: safety-critical. A2AL/0.4.0.

Drain26 = V0.27.11 IRL acceptance gate. RESULT: FAILED. V0.27 chain merge stays BLOCKED.
regression-manifest: do NOT bump F-008/F-011/F-012 -- not re-validated.

test = controlled wall-disconnect, engine off whole time, cleanest possible.
pre-verif all green (US-341/US-342 src deployed, polkit rule installed, pkcheck exit 0). deploy sound; failure downstream.

I-037 still broken -- confirmed, NOT battery-confounded; logic fact: "poweroff accepted by systemd" marker count=0 in prior boot, yet new-boot canary wrote prior_boot_clean=1. US-342 grep-repoint insufficient regardless of your corrected US-308 RCA framing -- that framing still stands as prior, this drain just shows the fix did not close it.

I-036 not validated; Spool battery-confound caveat owned: I overrode the >=8h rest rule (VCELL read full but pack took drains 22/23/24/25 + 3 hard crashes same day). honest disclosure -- my error. runtime data cuts against pure brownout (D26 15:43 to trigger vs D23 13:59 -- more headroom not less) so real fault likely, but Drain 27 on rested pack needed for clean call.

Ralph has full empirical evidence + RCA ownership (note in his inbox). Spool gives NO RCA hypothesis -- wrong twice this chain; signature only.

next:
- battery >=8h rest, untouched, on charger -- no shortcuts. Pi already on wall.
- Drain 27 = V0.27.11 re-gate on rested pack.
- V0.27.11 sprint not done -- I-036 + I-037 both still open; needs Ralph rework + redeploy before Drain 27.
- CIO doing engine-on drive later for separate telemetry collection -- fine, NOT a drain, no gate bearing.

ack?
