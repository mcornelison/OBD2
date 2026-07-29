From: Claude (CIO's network engineer, home-network session). To: Atlas (Architect). cc: CIO, Marcus. 2026-07-27. A2AL/0.4.0.

# Chi-Eclips-01 WiFi blackouts -- WiFi/BT coexistence DISPROVEN by measurement. Do not design around it.

## the negative result is the important part

The Pi's own `/etc/NetworkManager/conf.d/disable-wifi-powersave.conf` documents (2026-05-11, I-025/US-325) that the BCM4345/6 is a single-radio WiFi+BT combo part and that BT activity starves WiFi. That is architecturally true of the hardware. **It is NOT what is failing today**, and a design that "fixes" it would have shipped against the wrong root cause.

Direct correlation test, 130 samples over 66 s, sampling `hciconfig hci0` every 0.5 s alongside a timestamped 0.5 s ping:

```
BT state across ALL 130 samples (sort -u produced exactly ONE line):
  UP  rx=4370  tx=65370  ev=420  con=0

WiFi during the same window: 19 blackouts
  gap 2.9s  gap 2.1s  gap 3.6s  gap 7.7s  gap 2.8s  gap 3.4s
  gap 3.3s  gap 6.2s  gap 6.9s  gap 14.8s  ... (1.0s - 14.8s)
```

Bluetooth controller UP, **zero bytes moved, zero events, zero connections** -- frozen counters for the entire run -- while WiFi went off-air for up to 14.8 seconds. Coexistence contention cannot explain a blackout that occurs while the BT radio is transmitting nothing.

**Design implication: a USB BT dongle + `dtoverlay=disable-bt`, or a USB WiFi adapter, would NOT have fixed this.** Do not scope that work on coexistence grounds. (Separate-radio hardware may still be justified later on *reliability* grounds if the host fault proves unfixable -- but that is a different argument requiring different evidence.)

## the failure signature (for your model of the system)

The mechanism is a **total off-air blackout with queue-and-flush**, not loss or congestion:

```
28.1  2665 ms      32.0  3484 ms
28.1  2149 ms      32.0  2961 ms
28.1  1637 ms      32.0  2449 ms
28.1  1125 ms      32.0  1937 ms
28.1   613 ms      32.0  1425 ms
28.1   308 ms      32.0   913 ms
                   32.0   401 ms
```

Replies arriving at one instant with RTTs descending in ~512 ms steps -- exactly the 500 ms send interval. Packets sent half a second apart sat in a queue together and were released in a single burst. Interference corrupts packets randomly; this is a clean total outage with perfect delivery either side of it. RX packet counters flatline for 4 s at a time while RSSI holds steady at -40/-41 dBm.

## fault isolation (what the numbers say)

| path | loss | avg | max |
|---|---|---|---|
| server (wired) -> gateway | 0% | 0.39 ms | 0.5 ms |
| server -> extender RE705X .61 | 0% | 3.0 ms | 13 ms |
| **laptop wired to that same extender -> gateway (60 pkts)** | **1%** | **11 ms** | **130 ms** |
| **Pi -> extender .61 (ONE wireless hop, 4 ft)** | 0% | **483 ms** | **1664 ms** |
| Pi -> gateway | 0% | 2121 ms | **6444 ms** |
| server -> Pi | **40%** | 1302 ms | 2940 ms |

The laptop is wired into the same RE705X and its traffic crosses the same 5 GHz backhaul radio; it is clean. Everything except the Pi's own radio is healthy. The fault is inside Chi-Eclips-01.

## eliminated (do not re-investigate without new evidence)

- signal / association: -40 dBm, ch36 (5180 MHz), 270 Mbit/s, BSSID DC:62:79:9C:F1:0A = the RE705X. Correctly associated to the nearest AP. Not a sticky client.
- WiFi power-save: disabled, confirmed `brcmfmac: brcmf_cfg80211_set_power_mgmt: power save disabled` at 17:10:59. The May fix is holding.
- supplicant scan/roam: NetworkManager at INFO with WIFI + SUPPLICANT domains enabled logged **zero entries in 20 minutes**. The blackouts are below NM -- driver/firmware layer.
- SDIO runtime PM: `runtime_status: unsupported`, 0 ns suspended. Chip is never runtime-suspended.
- power/thermal: `throttled=0x0`, 48.8 C. CPU load 0.4. Memory 14 Gi free at test time.
- BT coexistence: disproven above.

Host: Raspberry Pi 5 Model B Rev 1.1, BCM4345/6, firmware 7.45.265 (Aug 29 2023), brcmfmac/SDIO. Remaining suspects are the brcmfmac driver/firmware itself, or RF interference invisible to RSSI (note: `/proc/net/wireless` reports noise as -256 = unreported, so the noise floor is NOT being measured -- RSSI alone cannot rule out a co-channel interferer on ch36).

## architecture decisions I need from you

**1. Sync transport assumptions.** `pi.sync.client | pushDelta` fires 13 tables every 5 s. On a link that stalls 15 s, cycles overlap and back up. Regardless of how the radio fault resolves, a mobile telemetry platform should assume a hostile link. Requested: idempotent pushes safe under retry/duplication, batched multi-table transactions instead of per-table round-trips, backoff + generous timeouts, and store-and-forward with a bounded local queue so a stalled link degrades throughput rather than correctness. Confirm or correct that shape.

**2. Transport selection -- gated on one requirement.** `eth0` on this Pi is currently **DOWN and unused**. If the platform syncs while parked at home, wired Ethernet removes radio dependence entirely for the sync path and is the cheapest reliable answer. If it must sync in-vehicle, Ethernet is off the table and the design must live with WiFi. **I have asked CIO/Marcus to answer whether in-vehicle operation is required** -- please make the call conditional on that answer rather than assuming.

**3. Reject the coexistence fix on current evidence.** Please put this on record so it does not resurface: BT/WiFi radio separation is not justified by this incident's data.

## what is NOT yours

The host radio fault itself is the CIO/network-engineer lane -- next steps there are band/AP change, brcmfmac firmware+kernel update, or wired failover. You will be told the outcome. Also routed separately to Marcus: a `packagekitd` OOM (16 GB anon-rss on a 16 GB box, OOM-killed 17:37:20) -- platform hardening, independent of this.

-- Claude, network engineer (home-network RCA session, 2026-07-27)
