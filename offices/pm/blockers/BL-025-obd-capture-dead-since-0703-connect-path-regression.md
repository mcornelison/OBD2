# BL-025: OBD BT capture DEAD since 2026-07-03 -- connect-path regression (TOP PROJECT BLOCKER)

| Field | Value |
|---|---|
| Severity | **P0 / project-blocking** (safety-relevant: no engine data for 25+ days) |
| Status | **FIX DEPLOYED + REBOOT-VERIFIED 2026-07-31 (V0.29.22).** Root cause = persistent Bluetooth SOFT-BLOCK (stale saved rfkill state restored every boot; Atlas live RCA). **US-514 (rfkill-unblock deploy-bake) + US-515 (pair_obdlink fix) shipped + deployed to the Pi (10.27.27.100); rebooted + verified GREEN: `rfkill` both `Soft blocked:no` SURVIVE the reboot, eclipse-rfkill-unblock enabled+active, eclipse-obd active, BT Powered:yes, .deploy-version=V0.29.22.** The capture killer is now repo-managed + reflash-proof. **REMAINING to fully close:** (a) engine-on pair + bond-survives-reboot + a captured drive (Spool's gate — `realtime_data` grows); (b) V0.29.23 hardening US-512 reconnect-transport-reset + US-513 origin RCA (groomed). |

## ✅ ROOT CAUSE FOUND + FIXED LIVE 2026-07-31 (Atlas + CIO on-Pi debug — supersedes ALL prior theories)

**THE root cause: a persistent Bluetooth soft-block.** `/var/lib/systemd/rfkill/platform-107d50c000.serial:bluetooth = [1]` — a **stale saved rfkill state** that `systemd-rfkill` **restores at every boot**, bringing Bluetooth up **soft-blocked** since ~07-03 → eclipse-obd can't use the dongle → **0 capture on every boot**. Pi-side, system-state, reboot-persistent (exactly the CIO's repeated diagnosis). Explains the intermittency: masking systemd-rfkill let BT come up unblocked (some sessions half-worked); reverting resumed the block.

**FIXED live (verified persistent across 2 reboots):** unblocked BT + installed/enabled `eclipse-rfkill-unblock.service` (oneshot `rfkill unblock all`, `After=systemd-rfkill.service bluetooth.service`). Post-reboot: hci0/phy0 Soft blocked = no, service active/enabled, BT Powered = yes, eclipse-obd active.

**This SUPERSEDES both prior theories:** the US-441/US-432 code-regression theory (wrong — Atlas owns the bad bisect, A-18) AND the "bonding is the primary cause" framing (bonding/reconnect-reset is now demoted to a **P1 hardening** item, not the headline). The 07-03 app code at most *amplified* WiFi coexistence; it did not cause the capture break.

### Resolution work (Atlas prioritized 2026-07-31)
1. **[P0/deploy — dispatched to Ralph]** Bake the radio-unblock into deploy: `deploy/eclipse-rfkill-unblock.service` + `deploy-pi.sh` install step + clear stale rfkill block on deploy. (Live fix is NOT in repo — a reflash would lose it.) **PM owes: version-bump + deploy on landing.**
2. **[P0 — dispatched to Ralph]** Fix `scripts/pair_obdlink.sh` (Trixie bluez prompt regex `[bluetoothctl]>` + display-capable agent for durable bond+trust). **PM owes: version-bump on landing.**
3. **[P1 — GROOM]** Durable bond + reconnect-transport-reset (Spool's path: disconnect → releaseRfcomm → re-bind → reconnect, not re-open `obd.OBD()` on a dead tty).
4. **[P1 — GROOM]** Root-cause WHY BT got soft-blocked ~07-03 (likely a debug-session rfkill that systemd-rfkill persisted). Unblock service is the safety net regardless.
5. **[P2/hardware — CIO sign-off]** Wired USB OBD adapter — Atlas standing rec; ends the whole BT-bond/discovery/coexistence class permanently.
6. **[validation]** Clean engine-on drive (Spool owns) — fresh `realtime_data`, single drive_id, key-on→drive→key-off = acceptance for BL-025/A-17.

**Deploy caveats (Atlas):** use normal `deploy-pi.sh` NOT `--init` (--init would wipe the live fix); post-deploy+reboot verify `rfkill list` both Soft blocked:no + service enabled + eclipse-obd active; pair_obdlink full bond-survives-reboot validation is engine-on (Spool).

---

## (Earlier) ROOT CAUSE CORRECTED 2026-07-31 (Spool live RCA — bonding theory, now itself refined to P1 by the rfkill finding above)
| Blocking | The entire IRL-validation gate (A-9/A-17/A-16-Bug3/BL-016) + all tuning value of the platform -- **the car captures nothing** |
| Filed | 2026-07-28 (PM, on CIO direction to investigate Spool's 07-27 RCA) |
| Refs | **CORRECTED RCA (2026-07-31):** `offices/architect/inbox/2026-07-31-from-spool-obd-bt-rootcause-consolidated.md` + `...-obd-connect-working-recipe.md`; tuner sessions.md S33. Original RCA: `.../2026-07-27-from-spool-obd-bt-capture-dead-since-0703.md`. US-441, US-432, F-117, A-17, BL-016; `src/pi/obdii/obd_connection.py` |

## ⚠️ ROOT CAUSE CORRECTED 2026-07-31 (Spool live RCA — supersedes the code-regression theory below)

The 07-03 code-regression theory (US-441 epoch-fence / US-432 PID-probe cache poisoning) is **SUPERSEDED**. Spool's live on-Pi RCA (2026-07-31) proves the fault is a **Bluetooth bonding + reconnect-recovery** problem, **NOT a code regression**:

- A **raw probe reproduces the drop** (so it's not the service's connect wrapper), and the **full service captures fine the instant the BT link is up** (so adapter/ECU/protocol are HEALTHY).
- Core defect = **bond-less pairing** (`Bonded:no`) → the link drops, and the service then retries a **stale rfcomm** forever instead of resetting the transport.
- WiFi/BT coexistence is **not fully ruled out** as a drive-time *aggravator* (Pi 5 CYW43455 shared radio) — but it is NOT the primary cause.

**DO NOT bisect US-441 / US-432.** That is the wrong tree; the code shipped 07-03 is not the root cause.

**Corrected fix path (Atlas's lane):** real **bond + trust** (not bond-less pairing) + **reconnect-resets-transport** (drop the stale rfcomm, re-bind) + 5GHz/scan mitigation (**never disable the radio** — see the stranded-Pi rule). Working recipe anchor: `obd.OBD(fast=False)`, rfcomm ch1, ISO 9141-2 auto (Spool's `probe_obd_capabilities.sh`). Spool verifies a captured drive (`realtime_data` grows) before this closes.

---

## Original theory (2026-07-27/28) — PRESERVED FOR AUDIT, now superseded by the correction above

## The finding (Spool RCA 2026-07-27, PM-verified live 2026-07-28)
OBD Bluetooth capture has produced **ZERO rows since drive 34 (2026-07-03)**. The CIO drove a 3-leg IRL drive on 2026-07-27 believing data was being collected -- captured nothing. **PM-verified on the Pi 2026-07-28:** `realtime_data` last row = `2026-07-03T21:33:53Z`; 588 connect events in the last 24h, none producing a row.

**Painful correction to the project record:** the V0.29.8→V0.29.18 narrative treated capture as "fixed (A-17/US-474), awaiting the IRL drive." That was WRONG -- the drive happened and capture is 100% dead. None of the V0.29.x work restored capture; the actual regression was never addressed.

## Root cause (Spool, well-evidenced)
A regression in `obd_connection.py`'s **connect path**, landed **2026-07-03** -- the exact day capture died -- by the two changes shipped that day:
- **US-441 (F-117/A-17):** `_ioLock` single-serialization + a generation/**epoch fence** (`ObdConnectionSupersededError` drops "superseded" reads).
- **US-432 (BL-016):** connect-time **supported-PID probe** (`_runSupportedPidProbe`) whose own docstring warns a **key-off connect poisons python-obd's `supported_commands` cache** + the engine-confirmed force-mandatory latch.

Dominant runtime error (248×/day): *"device reports readiness to read but returned no data (device disconnected or multiple access on port?)"* -- the same concurrent-`/dev/rfcomm0`-access class US-441 was meant to CLOSE.

**Known-working vs broken divergence (Spool):** the working probe recipe (`offices/tuner/scripts/probe_obd_capabilities.sh`) uses `obd.OBD(fast=False)` -- **auto-detect, no portstr**. The broken service forces `portstr=/dev/rfcommN` via its own rfcomm bind + wraps in the new `_ioLock`/epoch-fence + connect-time PID probe.

**Prime suspect (Spool):** the US-432 supported-PID probe running on key-off connects (every reconnect while parked) **poisons the `supported_commands` cache**, so even engine-on reads return nothing.

## Ruled out (do NOT re-chase)
Adapter/ECU/BT hardware (raw `obd.OBD(fast=False)` got live RPM on this MAC ~07-19); MAC (correct FB, US-477 guard held); second reader (single `main.py`); DriveDetector (never got data); power/boot (Pi up + attempting all day); **WiFi/BT coexistence** (separately DISPROVEN by the network-engineer RCA 07-27 -- the OBD app was exonerated twice).

## Path to resolution
1. **Atlas: bisect US-441 + US-432** (both 07-03) in the connect path -- prime suspect the US-432 key-off PID-probe cache poisoning; also the epoch-fence dropping live reads + forced-rfcomm vs auto-detect. → candidate fix.
2. **Spool isolation test (needs engine-on):** run `probe_obd_capabilities.sh` (known-working recipe) while the service logs 0 rows → confirms the regression is 100% in the service connect path, not hardware. Spool owns the engine-data verification.
3. **PM: groom the P0 fix as the next sprint** on Atlas's bisect ruling; Ralph builds; Spool verifies a clean captured drive (`realtime_data` grows) before this closes.
4. **Process:** run the US-479 pre-drive green-light (`verify_pre_drive.sh`) before EVERY drive -- it exercises the production capture path and would have shown CAPTURE: FAIL before the 07-27 blind drive.

## Resolution
[Fill in when a fix ships + a real drive captures rows.]
