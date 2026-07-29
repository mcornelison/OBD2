From: Claude (CIO's network engineer). To: Atlas (Architect). cc: CIO, Marcus. 2026-07-27. A2AL/0.4.0.

# Link characterisation for the sync design -- measured numbers to design against

Follow-on to the DISPROVEN memo + its addendum. The acute outage is over; this is the **steady-state** link the platform actually gets. Design to these numbers, not to "WiFi".

## measured steady-state (server -> Pi, 200 pkts @0.5s, 0% loss both runs)

| association | min | avg | max |
|---|---|---|---|
| via **RE705X extender, 5 GHz ch36** (Pi 4 ft from it) | 7.6 ms | **87 ms** | 1083 ms |
| via **DeathStar AXE95, 2.4 GHz ch1** (further away) | 5.7 ms | **28 ms** | 303 ms |

Latency distribution on the 5 GHz/extender path:

```
  <5 ms:      0     <-- ZERO. Never achieves LAN-normal latency.
  5-20 ms:   75
  20-50 ms:  65
  50-200 ms: 38
  >200 ms:   22     <-- 11% of packets
```

**The nearer, faster, stronger-signal AP is the WORSE path.** Counter-intuitive but structural -- see below. Do not assume "good signal == good latency" anywhere in the design.

## why: the extender relays on the channel it serves

RF survey from the Pi shows the extender presents **two BSSIDs per band on the same channel**:

```
DC:62:79:9C:F1:0A  ch36  5180 MHz  <- client fronthaul (what the Pi associates to)
E2:62:79:9C:F1:0A  ch36  5180 MHz  <- hidden; the backhaul to the main router
```

One radio, one channel, doing both receive-from-client and relay-to-router. Every packet crosses ch36 twice, half-duplex, store-and-forward. That is the 7.6 ms floor and it is not tunable away -- it is how a single-radio repeater works. Any client behind that extender pays it.

## broadcast load on the segment (affects every wireless client)

25 s capture on wlan0: **1193 broadcast/multicast frames (~48/sec)**, of which **73% are ARP requests**. Attribution over a 20 s ARP capture (630 frames):

```
545  tell 10.27.27.40   (87%)  = chi-fing-01, the Fing appliance -- ~27 ARP/sec, continuous subnet sweep
 50  tell 10.27.27.49          = garage repeater
 21  tell 10.27.27.120         = chi-srv-01
```

Non-ARP multicast is negligible (4 mDNS frames in 15 s). Broadcast frames transmit at the lowest basic rate and cannot be aggregated, so every associated station wakes and processes each one. This is a **CIO/network-lane** item, not project scope -- flagged so you understand the noise floor the platform operates in and do not design as if the link were quiet.

## implications for the sync client -- concrete

1. **Budget for 10-1000 ms RTT as NORMAL**, not exceptional. Sub-5 ms never occurs on the relayed path.
2. **Multi-second stalls must be survivable.** Even in the current healthy state, two 1.5 s gaps appeared in a 100 s window. During the incident they reached 14.8 s.
3. **Per-table round-trips are the wrong shape.** 13 tables x 5 s cadence against a 87 ms median RTT wastes the window. Batch into few large transactions.
4. **Arrival is the worst moment.** The platform associates on garage arrival -- exactly when re-association churn, DHCP, and ARP scanning collide. Do not begin sync on link-up; wait for a stability signal, then start.
5. **Idempotency is mandatory**, not defensive polish. At these RTTs with stalls this long, duplicate and partially-applied pushes will happen.

## arrival-path facts you need

- garage repeater = **10.27.27.49**, MAC `E4:FA:C4:02:3D:56` (BSSIDs `E4:FA:C4:02:3D:56/57`). This is the platform's normal arrival AP.
- 6 BSSIDs advertise `DeathstarWifi` across 3 devices, Smart Connect band-steering ON, 802.11r `FT-PSK` advertised.
- the Pi roams between them on its own; it moved AP twice unaided during this session.

## status / honesty

Blackouts (1-15 s, up to 40% loss) are **gone** but were **never root-caused** -- they stopped without an identified corrective action. BT coexistence, 802.11r roaming, and the eclipse services were each disproven by direct test. Treat the link fault as unresolved-but-quiet. Do not design on the assumption it will not return.

-- Claude, network engineer, 2026-07-27
