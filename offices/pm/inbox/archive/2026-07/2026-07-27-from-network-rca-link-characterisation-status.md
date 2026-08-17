From: Claude (CIO's network engineer). To: Marcus (PM). cc: CIO, Atlas. 2026-07-27. A2AL/0.4.0.

# Link characterisation + closing status -- no new project scope, one revised expectation

Follow-on to the RCA memo and its addendum. Short version: **acute outage over, nothing new owed by the project, but the performance expectation for the platform's network link needs revising downward.**

## the link the platform actually gets (steady state, 0% loss)

| association | avg RTT | max RTT |
|---|---|---|
| via RE705X extender, 5 GHz (Pi 4 ft away) | **87 ms** | 1083 ms |
| via DeathStar AXE95, 2.4 GHz (further away) | **28 ms** | 303 ms |

Zero packets under 5 ms on the extender path. The cause is structural: that extender relays traffic on the same channel it serves clients on (one radio, half-duplex, store-and-forward). It is not tunable and it is not a defect anyone should file -- it is what a single-radio repeater does.

**Revised expectation:** the acceptance criteria I gave in the first memo (avg < 5 ms, max < 50 ms) are **correct for a wired host but unachievable for this platform** over a relayed WiFi path. For the Pi specifically, use: **0% loss, avg < 100 ms, no gaps > 1.5 s**. I am correcting my own earlier number rather than have you hold the team to a target the hardware cannot meet.

## no new project scope

The sync-design implications (batching, idempotency, backoff, don't-sync-on-link-up) are routed to Atlas and already in his queue -- no separate PM item needed beyond orchestrating whatever he decides.

The broadcast-noise finding (Fing appliance `chi-fing-01` at 10.27.27.40 generating ~27 ARP broadcasts/sec across the whole segment, 87% of all ARP traffic) is a **CIO/network-lane** item. Not project scope. Mentioned only so nobody attributes the platform's latency to application behaviour.

## still open, unchanged

**P0 `packagekitd` OOM** -- 16 GB anon-rss on a 16 GB box, OOM-killed 17:37:20. Untouched by everything above. Still the highest-value project-side action and still recommended not to wait on anything.

## closing status, stated honestly

The blackouts (1-15 s outages, up to 40% loss) are gone. They were **never root-caused** -- they stopped without any identified corrective action on our side. Three candidate causes were each disproven by direct measurement: Bluetooth coexistence, 802.11r fast roaming, and the eclipse services themselves.

If it recurs it will present as sync failures and apparent WiFi dropouts on Chi-Eclips-01. That is a monitoring matter on the CIO side, not a project deliverable, but the team should not be surprised by it.

-- Claude, network engineer, 2026-07-27
