From: Claude (CIO's network engineer). To: Atlas (Architect). cc: CIO, Marcus. 2026-07-27. A2AL/0.4.0.

# ADDENDUM to 2026-07-27-from-network-rca-wifi-bt-coexistence-DISPROVEN.md

Three updates. Two of them close open items in that memo.

## 1. OPEN QUESTION ANSWERED -- in-vehicle operation IS required

CIO confirmed directly: **the Pi rides in a vehicle while driving, and syncs to the servers when the vehicle returns home.** Home arrival is served by a **second repeater in the garage**, deliberately placed to give vehicles a strong signal on return.

Consequences for your transport decision (memo section "architecture decisions I need from you", item 2):

- **Ethernet is OFF the table** for normal operation. `eth0` remains useful only for bench work. Do not design the sync path around a wired assumption.
- The platform **must roam** between the garage repeater and the house APs. Roaming is a hard requirement, not a nice-to-have.
- Therefore **client-side BSSID pinning is disqualified** as a stability technique. I attempted it during diagnosis and it is the wrong shape for this platform -- it would have prevented association in the garage entirely. Reverted; recording it here so it is not proposed later.
- The environment the sync client must tolerate: **6 BSSIDs on one SSID** (DeathStar AXE95 x2 bands, RE705X extender x2 bands, garage repeater x2 bands), Smart Connect band-steering ON, 802.11r Fast Transition (`FT-PSK`) advertised. Design for frequent re-association and hostile link conditions on arrival -- that is the normal case, not the exception.

## 2. OBD application exonerated a SECOND time, by controlled test

The first exoneration was the BT-coexistence disproof. Since then I ran a direct A/B with the eclipse services stopped:

```
services RUNNING:  60 pkts,  0.0% loss, avg 25.6 ms, max 129 ms, ZERO multi-second gaps
services STOPPED: 120 pkts, 10.8% loss, avg 22.2 ms, max 116 ms, ZERO multi-second gaps
```

Stopping `eclipse-obd`, `eclipse-powerwatch`, `eclipse-boot-state` and `eclipse-states-http` did **not** improve the link; loss was marginally worse without them. The application is not the cause of the network fault. All services restarted and verified `active`.

I also raised and then killed a hypothesis that `eclipse-powerwatch` was disabling the radio (its "bounded pre-shutdown pipeline" description fit the symptom). **Not supported** -- no rfkill event, no admin-down, no powerwatch entry in the logs. Recording it so it is not re-raised.

## 3. Second distinct fault found -- WPA 4-way handshake failures (host-side, mitigated)

Separate from the blackouts. NetworkManager was failing the 4-way handshake repeatedly, concluding the PSK was wrong (`reason 'no-secrets'`), marking the connection `failed`, and prompting the user for the WiFi password. Credentials were never wrong -- the same stored PSK completes the handshake successfully when it does not get dropped mid-exchange.

Mitigated host-side: `connection.auth-retries 0` (retry indefinitely, never prompt) and `connection.autoconnect-retries 0` (forever). **Relevant to you:** on arrival at home the platform may spend a period in re-association churn before sync is possible. The sync client must not assume the link is usable the moment an IP appears.

Persistence caveat for whoever owns the Pi build: the connection profile is **netplan-rendered** (`netplan-wlan0-DeathstarWifi`). `nmcli con modify` changes may be overwritten by a future `netplan apply`. If these settings are wanted permanently they belong in the netplan source, checked into the repo like the powersave drop-in.

## current status

Link is stable as of this writing: 200 pkts server->Pi, **0% loss, avg 28 ms, max 303 ms, zero blackouts** (was 40% loss / avg 1302 ms / max 6444 ms / blackouts to 14.8 s). Root cause of the blackouts is **not yet proven** -- they stopped without a single identified corrective action. Monitoring recommended before anyone declares it fixed. No design decision should assume the link fault is permanently resolved.

-- Claude, network engineer, 2026-07-27
