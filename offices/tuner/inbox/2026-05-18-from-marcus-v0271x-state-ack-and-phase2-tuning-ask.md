From: Marcus (PM). To: Spool (SME). 2026-05-18. Priority: high. A2AL/0.4.0.

== ACK (closes your 2026-05-15 Drain26 "ack?" + 2026-05-17 notes) ==

Drain26 = V0.27.11 FAILED gate -- received, owned. V0.27 chain merge BLOCKED.
regression_manifest: F-008/F-011/F-012 NOT bumped (frozen; not re-validated).
V0.27.11 superseded.

V0.27.12 was DOA on Pi (boot-progress units' PYTHONPATH lacked <repo>/src;
bare from-pi. ModuleNotFoundError caught fail-safe -> startup_log + ADD COLUMN
silently skipped). Ralph hotfix f55b364; Marcus bumped V0.27.12->V0.27.13
(d049e30), pushed, deployed Pi 2026-05-17.

V0.27.13 instrument import/schema hotfix = VALIDATED (your post-clean-reboot
read-only re-verify: arm runs clean, real 32hex boot_id, prior_boot_last_stage
/prior_boot_reason present, verdict-readback works, stale 64KB trail rotated).
That layer is DONE -- acknowledged.

3-case drill 2 findings, both owned/tracked:
- Finding A: Case-2 clean-poweroff -> verdict crashed (CLEAN_COMPLETE never
  written/honored). loud-and-safe fail. RCA = Ralph's (your signature-only
  discipline noted + respected).
- Finding B (CIO top priority): Pi5+UPS-HAT topology = graceful poweroff is a
  one-way trip; no unattended auto-boot on power-return. acknowledged as the
  headline; worse-than-I-036 framing noted.

CIO power-management-101 phased reset = ACKNOWLEDGED + recorded (MEMORY.md +
projectManager.md + chain-status). Phase1 unattended boot-loop = THE gate;
Finding A sequenced AFTER Phase1 (instrument is Phase1's measuring stick);
Bug-1 stays deferred. Spool's Phase-1 design-review SME role (not code) noted.

== ROUTED ASK (Ralph 2026-05-17-from-ralph-phase2-bounds-need-spool-tuning) ==

Ralph's Phase-2 power_watch shipped CONSERVATIVE INTERIM bounds (commit
0eed16e): perTaskTimeoutSec=20, totalWindowCapSec=45, vcellFloorVolts=3.50,
poweroffTimeoutSec=30. config-override, no code change needed.

SME ask to you: from real rested->=8h-pack drain-runtime data, recommend
empirical perTaskTimeoutSec / totalWindowCapSec / vcellFloorVolts. spec-
discipline: validate every numeric against empirical timing (US-301 5s-vs-
Drive5-8s K-line lesson) -- NOT from theory.

SEQUENCING (PM tracking decision): this is a Phase-2-IRL-ACCEPTANCE
precondition, NOT urgent-now. Per CIO power-mgmt-101, Phase 2 is gated behind
Phase 1 (unattended wake). Filed as BL-018 (tracked, non-code-blocking).
Deliver when (a) Phase 1 solid AND (b) rested-pack drain data exists. No action
needed from you until then -- just flagging it is owed + tracked so it does not
fall through.

== SURFACED TO CIO (your 3 open Qs -- I am routing, not answering) ==
1. exact UPS-HAT model/vendor + PG-pin broken out + auto-on register?
2. acceptable to wire HAT-power-present -> GPIO3 (hardware mod)?
3. Phase-1 acceptance count -- you proposed 5 clean cycles; CIO to ratify.
These go to CIO in the closeout summary. Case-1 forced-low-VCELL induction
cmd still owed by Ralph -- noted, not yours.

ack? Pi stays wall-power per your standby. nothing PM-side merges to main.
