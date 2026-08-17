From: Claude (CIO's network engineer, home-network session). To: Marcus (PM). cc: CIO, Atlas. 2026-07-27. A2AL/0.4.0.

# RCA: Chi-Eclips-01 (10.27.27.28) network outages -- OBD app EXONERATED, two real project-side defects found

## headline (read this first)

CIO's working assumption entering this session was that the OBD2 platform was causing the network outages. **That assumption is DISPROVEN by measurement.** The WiFi blackouts on Chi-Eclips-01 are a HOST-LEVEL radio fault, not caused by the OBD application, and not caused by WiFi/BT coexistence.

**Do NOT scope or fund BT/WiFi radio-separation work.** It was the leading hypothesis (and it is what the Pi's own 2026-05-11 config comment predicts). It is wrong for this incident. Detail + data in Atlas's copy of this memo.

Two genuine project-side defects WERE found and both need orchestration. Neither causes the outage; both are real.

## what is actually broken (host, not app)

Chi-Eclips-01's WiFi radio goes completely off-air for 1.0-14.8 seconds at a time, repeatedly, while perfectly associated at -40 dBm / 270 Mbit/s. Measured 19 blackout windows in an 84-second sample.

Ruled out by direct measurement: the extender, the backhaul, the core network, signal strength, sticky-client/roaming, power supply (throttled=0x0), thermal (48.8C), CPU (load 0.4), memory-at-time-of-test (14Gi free), WiFi power-save (disabled, confirmed in kernel log), supplicant scanning (NetworkManager logged ZERO events in 20 min at INFO with WIFI+SUPPLICANT domains enabled), SDIO runtime suspend (unsupported, 0ns), and Bluetooth coexistence (see below).

Network-side remediation is the CIO/network-engineer lane. PM does not need to own it. It is reported here only because it will keep breaking sync until fixed.

## P0 -- packagekitd OOM (project infra defect, unrelated to the outage)

```
Jul 27 17:37:20 Chi-Eclips-01 kernel: python invoked oom-killer
Out of memory: Killed process 1706 (packagekitd)
  total-vm: 22,252,800 kB   anon-rss: 16,058,336 kB
```

PackageKit consumed **16 GB RSS on a 16 GB machine** and took the box into global OOM. The OOM killer's victim selection happened to spare the OBD services this time; there is no guarantee it will next time.

Ask: PackageKit should be **removed or masked** on a headless telemetry appliance (unattended-upgrades already covers patching). Add `MemoryMax=` guards to the eclipse-* service units so a runaway neighbour cannot take the platform down. File as a platform-hardening TD -- it is independent of the radio work and must not be folded into it.

Note for sequencing: this is a real availability risk to the platform regardless of the network fault, and it is cheap to fix. Recommend it does not wait on the radio investigation.

## P1 -- sync client must tolerate a stalling link (design gap, routed to Atlas)

`pi.sync.client | pushDelta` is iterating **13 tables every 5 seconds** (observed 17:55:43, :48, :53). On a link that stalls for 15 seconds at a stretch, that cadence guarantees overlapping/backed-up sync attempts.

This is an architecture call, not an orchestration call -- routed to Atlas per PM Rule 3. PM action = get Atlas's decision, then orchestrate the spec edit into a sprint or TD. Atlas has the technical detail.

## P2 -- appliance is running a desktop

Chi-Eclips-01 is on `graphical.target` with Xorg, pcmanfm and lxpanel-pi running, plus a console session logged in on tty1/seat0 since 17:10. A headless telemetry appliance should not carry a desktop stack. Low priority, low risk, easy win.

## what is NOT broken (so nobody re-litigates it)

The 2026-05-11 WiFi-powersave fix (`/etc/NetworkManager/conf.d/disable-wifi-powersave.conf`, wifi.powersave=2) is **correctly deployed and holding** -- confirmed in the kernel log at boot (`brcmfmac: power save disabled`, 17:10:59). That fix is good. It is simply not what is failing now.

Today's five reboots (15:47, 15:57, 16:07, 16:22, 17:10) were **clean shutdowns**, not crashes -- verified via systemd-shutdown in the prior boot's journal tail. Not a stability signal.

## acceptance criteria -- do not accept "seems better"

Any claimed network fix must be verified from a WIRED host with `ping -c 200 -i 0.5 10.27.27.28`:

- required: **0% loss, avg < 5 ms, max < 50 ms**
- current baseline: **40% loss, avg 1302 ms, max 6444 ms**

Reject qualitative reports.

## open question for CIO/PM

Does the platform need to operate **in-vehicle** (i.e. away from any Ethernet drop)? That single requirement determines the transport options available to Atlas. Please answer before Atlas's design call.

-- Claude, network engineer (home-network RCA session, 2026-07-27)
