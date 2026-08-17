From: Claude (CIO's network engineer). To: Marcus (PM). cc: CIO, Atlas. 2026-07-27. A2AL/0.4.0.

# ADDENDUM to 2026-07-27-from-network-rca-pi-wifi-blackouts-and-packagekit-oom.md

## 1. open question ANSWERED -- routed to Atlas

CIO confirmed: **in-vehicle operation IS required.** The Pi rides in a vehicle and syncs on return home via a dedicated **garage repeater**. Ethernet is therefore off the table for normal operation, and the platform must roam. Atlas has the full detail and can now make the transport call that was gated on this answer -- PM can unblock that item.

## 2. OBD application exonerated a second time (controlled A/B)

```
services RUNNING:  60 pkts,  0.0% loss, avg 25.6 ms, ZERO multi-second gaps
services STOPPED: 120 pkts, 10.8% loss, avg 22.2 ms, ZERO multi-second gaps
```

Stopping all four eclipse services did not improve the link. The application is not causing the network outage. All services restarted, verified `active`. No project remediation is owed for the outage itself.

A hypothesis that `eclipse-powerwatch` was switching the radio off was raised and **disproven** (no rfkill, no admin-down, no log entries). Noted here so it does not resurface as scope.

## 3. status -- outage resolved, root cause NOT proven

| metric (server -> Pi, 200 pkts) | session start | now |
|---|---|---|
| packet loss | 40% | **0%** |
| average RTT | 1302 ms | **28 ms** |
| max RTT | 6444 ms | 303 ms |
| multi-second blackouts | up to 14.8 s | **none** |

Honest caveat for planning: the blackouts stopped **without a single identified corrective action**. Do not treat this as a closed root-cause. If it recurs it will present as sync failures and apparent WiFi dropouts.

## 4. P0 unchanged -- packagekitd OOM still needs fixing

The 16 GB `packagekitd` runaway (OOM-killed 17:37:20) is untouched by any of the above and remains the highest-value project-side action. Recommend it does not wait on anything else.

## 5. one item for whoever owns the Pi build

Two NetworkManager settings were applied host-side to stop the box prompting the user for the WiFi password (`connection.auth-retries 0`, `connection.autoconnect-retries 0`). The profile is **netplan-rendered**, so a future `netplan apply` may revert them. If wanted permanently they belong in the netplan source in the repo, same pattern as the existing wifi-powersave drop-in.

-- Claude, network engineer, 2026-07-27
