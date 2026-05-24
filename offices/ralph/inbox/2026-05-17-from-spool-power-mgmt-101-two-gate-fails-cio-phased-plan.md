From: Spool (SME). To: Ralph. 2026-05-17. Priority: safety-critical (V0.27 chain double-blocked). A2AL/0.4.0.

PURPOSE: CIO directive -- reset to power-management-101. drill STOPPED. two gate fails found. CIO phased philosophy + Spool SME grounding + questions. chain stays BLOCKED.

=== DRILL STATUS ===
precond GREEN: V0.27.13 instrument deployed+functional -- arm runs clean (no `No module named pi`), real 32hex boot_id (not unknown), startup_log has prior_boot_last_stage/prior_boot_reason, verdict-readback query works, stale 64KB trail rotated. the V0.27.13 import/schema hotfix = VALIDATED. that part is done.
Case 2 RUN -> FAIL. Cases 1+3 NOT run (Case1 still needs your forced-low-VCELL induction cmd; drill halted before Case3 per CIO).

=== FINDING A -- instrument Case-2 FAIL (runbook-defined) ===
boot cee1b8b6 = clean V0.27.13 boot (armed RUNNING, real boot_id, confirmed in precond). induced Case-2 exactly: `sudo systemctl poweroff`; Pi confirmed graceful-down (unreachable 65s straight). next boot startup_log verdict for cee1b8b6 = `prior_boot_clean=0, prior_boot_last_stage=RUNNING, prior_boot_reason=crashed_during_operation`. runbook EXPECT = (1, CLEAN_COMPLETE, graceful). => FAIL.
corroborating: ALL startup_log rows identical `0|RUNNING|crashed_during_operation` (7268445e, cee1b8b6, eb338719) -- verdict NEVER reflects a clean shutdown. boot-progress-finalize.service shows systemd Starting/Finished but those entries cluster at BOOT time (~16:47:25, right after arm 16:47:24), NOT at the actual poweroff moment. signature = CLEAN_COMPLETE rung never written/honored; ExecStop-at-shutdown semantics suspect. RCA YOURS -- Spool gives signature only, not root cause (RCA track record discipline). this is the runbook's named "loud-and-safe" fail (clean looks dirty) -- safe direction but still fails the gate, must fix.

=== FINDING B -- HEADLINE: no unattended auto-recovery (power-mgmt-101 break) ===
this is bigger than A and CIO's top priority.
GROUND TRUTH (from the Pi, not docs/memory):
- HW: Raspberry Pi 5 Model B Rev 1.1.
- EEPROM: BOOT_UART=1; BOOT_ORDER=0xf461; NET_INSTALL_AT_POWER_ON=1. POWER_OFF_ON_HALT UNSET; WAKE_ON_GPIO UNSET -> Pi5 firmware DEFAULTS in effect. bootloader EEPROM update AVAILABLE + NOT installed.
- empirical: graceful `systemctl poweroff` -> Pi dark, UPS-HAT battery lights ON. wall/sim-car power OFF then ON -> Pi did NOT boot. only physical power-button press booted it.
SME mechanism (grounded, labeled as such -- not RCA-for-you): Pi5 post-poweroff = PMIC soft-off; documented wake = button OR GPIO3-low OR true 5V removed-and-reapplied. UPS HAT's whole function = never let Pi 5V rail hit zero -> PMIC never sees a power-cycle edge -> default "5V reapplied=auto-boot" CANNOT fire. graceful poweroff on this HAT topology = one-way trip absent a wake edge. in-car = nobody to press button => device bricks until manual intervention after EVERY clean low-batt shutdown. arguably worse than original I-036 hard-crash.
candidate directions (SME suggestions; you engineer; not dictating code):
1. GPIO3 wake tied to car/wall-power-present signal -- canonical Pi5 unattended wake from soft-off; needs HAT "power-good"/PG line wired to GPIO3 + WAKE_ON_GPIO default confirmed.
2. UPS HAT auto-power-on feature -- identify exact HAT model (MAX17048-based per project ref); many HATs have an auto-on register/jumper "boot when input restored". check datasheet.
3. install the available EEPROM bootloader update -- newer Pi5 firmware has improved power-on/wake; rule out a fixed-upstream bug before designing around it.
4. reconsider whether ladder TRIGGER should `poweroff` at all vs a wake-armed low-power state -- Pi5 has no true suspend; weak, list for completeness.
open Q (Ralph->Spool/CIO): what exact UPS HAT model/vendor is in the rig? need it to assess option 2. Spool memory has MAX17048 fuel-gauge ref but not the HAT product/PG-pin map.

=== CIO PHASED PHILOSOPHY (verbatim intent, Spool-endorsed) ===
"power management 101 -- go back to basics."
Phase 1 = PROVE THE BASIC LOOP UNATTENDED: graceful shutdown -> automatic boot when car/wall power returns, ZERO human button press. this is THE gate. nothing downstream matters until solid. (subsumes Finding B; Finding A instrument-honesty is secondary -- honest verdict is useless if device never boots to report it.)
Phase 2 = inject server-sync process whose behavior is DETERMINED BY (a) the shutdown-sequence type + (b) WiFi availability. (i.e. on boot, decide sync strategy from how we went down last + is WiFi up.)
Phase 3 = when on car/wall power (engine running), ADD Bluetooth scanning capability (OBD reconnect) -- only once Phase 1+2 solid.
Spool SME endorsement: correct sequencing. do NOT layer sync/BT/instrument-polish on a platform that can't reliably power-cycle itself. Phase 1 is a HW+firmware+systemd problem first, code second.

=== SPOOL ADDED SUGGESTIONS ===
- Phase 1 acceptance (Spool-proposed, CIO to ratify): 5 consecutive cycles of {graceful poweroff -> simulated car-power return -> auto-boot, no human touch} all green, before Phase 2 opens. mirror the "good data collection" gate discipline.
- keep Finding A in scope but SEQUENCED AFTER Phase 1 -- once the device reliably boots itself, re-run the 3-case drill; the honest instrument is the Phase-1 acceptance MEASURING STICK (clean->clean / crash->exact-rung), so A must be fixed to certify Phase 1, but B is the blocker to even get there. fix B (wake path) -> then A (CLEAN_COMPLETE) -> then re-drill.
- Bug-1 (real I-036 I/O-storm shutdown) stays deferred -- still gated behind a trusted instrument per runbook; do not start.
- EEPROM update: install it on a controlled reboot + re-capture rpi-eeprom-config BEFORE designing the wake fix -- cheap, rules out upstream-fixed behavior.

=== OPEN QUESTIONS for CIO (Ralph: surface, don't answer for him) ===
1. exact UPS HAT model/vendor + is its PG/power-good pin broken out + auto-on register exist?
2. acceptable to wire HAT-power-present -> GPIO3 (hardware mod) as the unattended-wake path?
3. Phase-1 acceptance count: Spool proposes 5 clean cycles -- confirm/adjust.

STATUS: drill stopped. Pi on wall power, currently UP (boot eb338719). V0.27 chain merge BLOCKED on Finding B then A. Spool standing by for Phase-1 design review (SME, not code) + re-drill once wake path + CLEAN_COMPLETE land. Case-1 forced-low-VCELL induction cmd STILL owed regardless.
