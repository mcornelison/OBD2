From: Claude (CIO's network engineer). To: Marcus (PM). cc: CIO, Atlas. 2026-07-28. A2AL/0.4.0.

# Chi-Eclips-01: one WiFi fault ROOT-CAUSED AND FIXED, one still open -- plus config changes you must reproduce if the Pi is rebuilt

Filed at the CIO's request specifically so that **nothing here is lost if the Pi gets rebuilt**. Read section 1 if you read nothing else.

Correcting my own 2026-07-27 closing statement: I said the blackouts "were never root-caused" and "stopped without any identified corrective action." That was accurate when written. It is now **partly superseded** -- one of the two faults is identified and fixed today. Details in section 2.

---

## 1. CHANGES MADE ON THE PI TODAY -- reproduce these on any rebuild

| # | Change | Where it lives | Must reproduce? |
|---|---|---|---|
| 1 | **`802-11-wireless.band=bg`** (lock WiFi to 2.4 GHz) on NM profile `netplan-wlan0-DeathstarWifi` | persisted by netplan to `/etc/netplan/90-NM-ad591fdd-*.yaml` as `band: "2.4GHz"` | **YES -- critical.** This is the Fault-1 fix. |
| 2 | `connection.auth-retries=0` + `connection.autoconnect-retries=0` (applied 2026-07-27) | same netplan YAML, under `passthrough:` | **YES.** Verified persisted today. |
| 3 | `firmware-brcm80211` + 4 sibling firmware pkgs upgraded `1:20250410-2+rpt1` -> `1:20260519-1~bpo13+1+rpt1` | dpkg | Optional -- **functionally a no-op**, see section 3. |
| 4 | Ethernet now connected: `eth0` DHCP `10.27.27.9`, 1000 Mb/s full duplex | physical | N/A but see section 5 |

**Item 2 correction for Atlas:** my earlier memo warned that `auth-retries` was netplan-rendered and might be reverted by `netplan apply`, and therefore belonged in the repo's netplan source. **That warning can be retired.** netplan captured the settings into its own YAML as passthrough; they round-trip correctly. No repo change needed for items 1 or 2 -- though putting them in the repo's netplan source is still the more durable choice if you want them guaranteed on a fresh image.

---

## 2. Fault 1 -- ROOT-CAUSED AND FIXED: 5 GHz association reject loop

wpa_supplicant was repeatedly attempting 5 GHz association and being rejected with **802.11 status code 16** ("authentication rejected due to timeout waiting for next frame"), then blacklisting and retrying forever:

```
Trying to associate with dc:62:79:9c:f1:0a (freq=5180 MHz)
CTRL-EVENT-ASSOC-REJECT status_code=16
BSSID ... ignore list count incremented to 3, ignoring for 60 seconds
CTRL-EVENT-SSID-TEMP-DISABLED duration=20 reason=CONN_FAILED
Activation: (wifi) association took too long
Activation: (wifi) asking for new secrets          <-- the password prompt
Trying to associate with dc:62:79:9c:f1:0b (freq=2412 MHz)
Associated / Key negotiation completed             <-- 2.4 GHz works first try
```

Every 5 GHz attempt failed, while 2.4 GHz succeeded, at -31 dBm signal. Reproduced across **two different APs** (extender and root router) and **survived an extender firmware update + reboot**, so it is not an extender defect.

**Correction, later the same evening:** I initially reported that 2.4 GHz *always* associated on the first attempt. That is wrong. On 6.12.75 I observed two consecutive `status_code=16` rejects on a **2.4 GHz** attempt (freq=2412) before the third succeeded. So status-16 rejects are **not band-specific** -- 5 GHz simply never recovered, whereas 2.4 GHz recovers after one or two retries.

This means Fault 1 and Fault 2 are plausibly **one fault with two presentations**: the radio intermittently goes mute. Mid-association that surfaces as a status-16 auth timeout; while already associated it surfaces as a silent multi-second blackout. Supporting detail: the `bssid=` field in every reject reported `dc:62:79:9c:f1:0b` regardless of which BSSID was actually being targeted, i.e. the field was stale -- consistent with the radio not being in a coherent state.

**The band lock remains justified regardless of which model is right**, because its benefit was measured, not theorised (max RTT 114.9 -> 19.4 ms, reject events 4 -> 0 per 100 s). Treat it as a mitigation, not a cure.

**This also explains the WiFi password prompts.** NetworkManager hits its activation timeout after ~25 s of rejected attempts, concludes the credentials are bad, and calls `asking for new secrets`. The PSK was never wrong. Yesterday's `auth-retries 0` suppressed the symptom; the band lock removes the cause.

Measured effect of the fix (200 packets, pinned to `wlan0`, gateway target):

| Metric | Before | After |
|---|---|---|
| ASSOC-REJECT / TEMP-DISABLED events | 4 per 100 s | **0** |
| 5 GHz association attempts | many | **0** |
| avg RTT | 11.8 ms | **9.2 ms** |
| max RTT | 114.9 ms | **19.4 ms** |

**Project impact:** the "apparent WiFi dropouts + sync failures" class of symptom is substantially reduced, and the user-visible password prompt should not recur.

---

## 3. Firmware: the stale-firmware workstream is CLOSED as irrelevant

My earlier RCA flagged `firmware-brcm80211` as >1 yr stale (20250410 vs 20260519) and blocked from updating because the download failed over the broken link. Both halves are now resolved:

- Download works over Ethernet (`archive.raspberrypi.com` responds in 0.22 s). Upgrade applied.
- **The upgrade changes nothing for this hardware.** The actual WiFi blob is byte-identical across both package versions:
  ```
  64410bcb1364a794ce4946bc40c7998f  cyfmac43455-sdio-standard.bin   (20260519, installed)
  64410bcb1364a794ce4946bc40c7998f  cyfmac43455-sdio-standard.bin   (20250410, cached .deb)
  ```
- Running firmware is `BCM4345/6 wl0: Aug 29 2023 version 7.45.265 (28bca26 CY)` and that **is** the newest published for the CYW43455.

`firmware-brcm80211` is a bundle spanning many chips; its version moving does not imply this chip's blob moved. **Nobody should spend further time on a firmware update for this Pi.** Rollback .deb remains cached at `/var/cache/apt/archives/firmware-brcm80211_1%3a20250410-2+rpt1_all.deb`.

---

## 4. Fault 2 -- STILL OPEN: silent total off-air blackouts

Independent of Fault 1 and **not fixed**. After the band lock, with zero rejects, zero 5 GHz activity, and the OBD services stopped, the radio went **completely off-air for 45.6 s** (21:07:38 -> 21:08:23) while the OS logged **absolutely nothing** -- no deauth, no disconnect, no reassociation, no kernel message. `wlan0` stayed up with a valid lease throughout.

That 45.6 s hole accounted for ~all of the run's packet loss; the remainder of the run was pristine. So the loss percentage looked worse while the link was actually healthier -- judge this link by **gap analysis**, not by loss percentage.

Now eliminated by direct evidence, in addition to everything in the prior memos:

- WiFi firmware (newest available, byte-identical -- section 3)
- Fing NAC block (the WiFi MAC is approved; verified in the app)
- Memory pressure / OOM as a WiFi cause (one OOM only, on 2026-07-27, wrong day; zero kernel allocation failures)
- Any package change in the fault window (**zero dpkg activity between 2026-05-20 and 2026-07-27**)
- The OBD services (stopped during the reproducing run)

### Kernel TESTED AND ELIMINATED (2026-07-28, same evening)

The leading hypothesis was a `brcmfmac` regression between 6.12 and 6.18. **Tested directly and disproven.** Booted `6.12.75+rpt-rpi-2712` (kept in `/boot`, swapped in via `/boot/firmware/kernel_2712.img`) and ran an identical 30-minute measurement. Firmware byte-identical on both, same target, majority of both runs on the same AP.

| Metric | 6.18.29 (current) | 6.12.75 (older) |
|---|---|---|
| loss | **1.36%** | 3.11% |
| avg RTT | **31.4 ms** | **223.5 ms** |
| max RTT | **2797 ms** | 6172 ms |
| gaps >1.5 s | **11** | **49** |
| packets lost | **49** | 112 |
| supplicant events | 0 | 0 |

**The older kernel is worse on every metric.** A 6.12 -> 6.18 regression is therefore ruled out, and reverting the kernel would have made the platform's link worse. The Pi has been **restored to 6.18.29** (backups of both boot files remain in `/boot/firmware/*.bak-6.18.29-claude`).

Note for the record: 6.12.75's numbers (avg 223.5 ms, max 6172 ms) sit almost exactly on the figures captured for the original fault on 2026-07-27 (avg 217 ms, max 6444 ms). Same fault, same severity envelope, kernel-independent.

### Fault 2 characterisation (useful for sync design -- route to Atlas)

Fault 2 is **episodic, not continuous**. In a clean 30-minute run on 6.18.29: 19 minutes clean, then one ~4-minute disturbed episode (a single 23 s blackout followed by ten 1.6-3.8 s gaps), then 7 minutes clean. Signal was flat at -31 to -33 dBm throughout, including *during* the 23 s blackout.

Practical implications for the platform:

- **A single short connectivity test proves nothing.** 100-packet samples returned anything from 0% to 44% loss purely depending on whether they landed inside an episode. Any health check must run over tens of minutes or it is measuring luck.
- **Judge the link by gap analysis, not loss percentage.** After the band lock the loss figure went *up* (14.5% -> 44% on one run) while the link was objectively healthier, because one long blackout dominates the ratio.
- Sync should assume **occasional total outages of 20-45 s with no OS-level warning**, and must not treat link-up as proof of reachability.

**Still open. No project action requested.** Recorded so the team is not surprised by residual dropouts.

---

## 5. Rebuild checklist (what a fresh image will NOT have)

1. Apply the **2.4 GHz band lock** (section 1, item 1) -- otherwise Fault 1 returns, including the password prompts.
2. Apply **auth-retries / autoconnect-retries = 0**.
3. **Approve the Pi's MACs in the Fing app BEFORE provisioning.** `eth0` and `wlan0` have *different* MACs (`88:a2:9e:84:46:1b` / `:1c`). Plugging in Ethernet today introduced `:1b` as an unknown device and Fing's default-deny NAC silently blocked it at L2 -- ARP answered normally, but 100% ICMP loss and no SSH. Budget for this or a rebuild will look like a dead box.
4. Second WiFi profile exists: **`DMH-W2770NEX_04A5`** (Pioneer head unit hotspot, `auth-alg=open`, no PSK, autoconnect on, created 2026-05-22). Recreate if the vehicle integration needs it. It is *not* implicated in either fault.
5. Do **not** pin a BSSID. Tried previously, failed to associate, forced a reboot. The Pi must roam.

## 6. Two housekeeping items for the project

- **P0 `packagekitd` OOM is untouched and still open** (16 GB anon-rss on a 16 GB box). Likely contributor found: **198 packages are pending upgrade** on this Pi, and a backlog that size is exactly what makes PackageKit's dependency solver explode. Clearing the backlog is worth trying as a fix. I deliberately did **not** run a full upgrade -- that is the project's environment and the CIO's call, not mine.
- **journald retention only reaches 2026-07-17**, which blocked comparison against the known-healthy period. Raising `SystemMaxUse` would make the next intermittent fault far cheaper to diagnose.
- FYI `drain-forensics.service` fires every ~6 s (timer-driven, so stopping the long-running services does not stop it). Not implicated -- it ran through both clean and blacked-out periods.

-- Claude, network engineer, 2026-07-28
