from=Atlas(Architect); to=Marcus(PM); date=2026-07-31; topic=STATUS: BT-soft-block-at-boot root cause FOUND+FIXED (persistent) + open work list; audience=agent; urgency=high; refs=BL-025,A-17,A-18,US-500,V0.29.20,V0.29.21

# STATUS to PM — capture RCA breakthrough + everything that still needs doing

CIO ran a live debug session with me on the Pi (bench, `10.27.27.100`, V0.29.21). Full status + a prioritized work list for you to groom.

## HEADLINE — the capture root cause was a persistent Bluetooth soft-block (found + fixed live, verified across 2 reboots)
- **`/var/lib/systemd/rfkill/platform-107d50c000.serial:bluetooth = [1]`** — a **stale saved rfkill state** that `systemd-rfkill` **restores at every boot**, bringing **Bluetooth up soft-blocked**. eclipse-obd then can't use the dongle → **0 capture on every boot** since the block was saved (~07-03). The phone bonds fine because that's the phone's own radio, not the Pi's blocked one.
- **This is Pi-side, system-state, and reboot-persistent** — exactly the CIO's repeated diagnosis. It also explains the intermittency: when I *masked* systemd-rfkill (07-31) BT came up unblocked (some sessions half-worked); when the mask was reverted, the block restore resumed.
- **FIX (live, verified persistent):** unblocked BT + installed & enabled `eclipse-rfkill-unblock.service` (oneshot `rfkill unblock all`, `After=systemd-rfkill.service bluetooth.service`). After a reboot: **hci0 Soft blocked: no, phy0 Soft blocked: no, service active/enabled, BT Powered: yes, eclipse-obd active.** Radios now come up unblocked and stay unblocked.

## Correction to the record (own it)
My earlier **US-441 `_ioLock` bisect was WRONG** (Spool + a 7-agent Opus RCA both refute it). The real capture blocker was **not** 07-03 app code — it was the **BT soft-block + bonding-layer**. The 07-03 code (US-441/432/404) at most *amplified* WiFi coexistence, it didn't cause the capture break. A-18 in my charter.

## OPEN WORK — please groom (prioritized)
1. **[P0 / deploy — load-bearing] Bake the radio-unblock into the deploy.** My `eclipse-rfkill-unblock.service` is **live on the Pi but NOT in the repo/deploy** — a full `deploy-pi.sh --init` or reflash would lose it and BT would go dark again. Ralph: add `deploy/eclipse-rfkill-unblock.service` + install step in `deploy-pi.sh`, and clear the stale `/var/lib/systemd/rfkill/*:bluetooth` block on deploy. (This is the durable version of tonight's fix.)
2. **[P0] Fix `scripts/pair_obdlink.sh` — it is broken.** Its pexpect prompt regex expects `[...]#` but Trixie bluez prompts `[bluetoothctl]>`, so it times out and never pairs/trusts. This is why no re-pair works. Ralph: fix the regex + use a display-capable agent (`KeyboardDisplay`/`DisplayYesNo`, not `NoInputNoOutput`) so a **durable bond + `trust`** is written and survives reboot.
3. **[P1] Durable bond + reconnect-transport-reset** (Spool's fix path, `inbox/2026-07-31-from-spool-obd-bt-rootcause-consolidated.md`): pairing must persist a link key + trust; reconnect on failure must **reset the transport** (disconnect → releaseRfcomm → re-bind → reconnect) instead of re-opening `obd.OBD()` on a dead tty.
4. **[P1] Root-cause WHY BT got soft-blocked (~07-03)** — likely a debug-session `rfkill`/reset that systemd-rfkill then persisted. Confirm origin so it can't recur; the unblock service is the safety net regardless.
5. **[P2 / hardware] Wired USB OBD adapter** — my standing recommendation; ends the entire BT-bond/discovery/coexistence class permanently. Worth CIO sign-off.
6. **[validation] Clean engine-on drive** — Spool owns engine-data verification: once BT is unblocked (done) + a durable bond exists (work item 2), confirm a full key-on→drive→key-off capture (fresh `realtime_data`, single drive_id). That's the acceptance for BL-025/A-17.

## Other status (unchanged, FYI)
- **V0.29.20 carousel-SSOT-wiring** — Atlas PASS given; branch `sprint/sprint66-V0.29.20` exists, ready for Ralph. US-478 IMU hardware pre-flight MET (0x69 + WHO_AM_I 0xEA). `states/imu` schema rendered.
- **US-500 IMU temp hotfix** — shipped in **V0.29.21** (`a6aa088`), deployed to the Pi. Needs the on-Pi `states/imu` render check (folds into the V0.29.20 validation).
- **systemd-rfkill / WiFi-off** cleanup done (radios stock, unblocked, persistent).

Net: the capture break has a confirmed Pi-side root cause that's now fixed at the radio layer; the remaining work is durable bonding (broken tooling) + baking tonight's fix into deploy + a validation drive. I'll design-gate any PRD you spin from items 1-3.

— Atlas
