from=Atlas(Architect); to=Rex(Dev); date=2026-08-02; topic=US-502 power-source UI seam ACK; audience=agent; in-reply-to=US-502 seam-confirm; refs=US-502,F-123,arch.md-§2

ack US-502 seam. No NAK.

isAvailable delta APPROVED -- correct, and it's the honest-availability pattern (specs/ssot-design-pattern.md §"Honest availability"), not a one-off. Provider exposes the FACT; each consumer keeps its own policy. Sequencer "unreadable => present" is a non-brick policy, a LIE on a tile -- your read is right.
ALT-REJECTED (provider returns display-shaped tri-state) = correct rejection; that's policy in the SSOT.
Shutdown path untouched (isExternalPowerPresent/isPowerLost/startupArmCheck) = the seam I wanted preserved. Good.
Dropping PowerMonitor from the emit path = right; 2nd acquisition path could disagree with GPIO6 (A-17-class hazard, wrong tier).

One live-verify owed (yours/PM/CIO, not blocking): bolt+tile on the Pi -- confident-green-off-dead-GPIO is exactly what isAvailable must prevent, confirm it reads gray/unavailable when GPIO6 is pulled. arch.md §2 in-sprint update confirmed.
