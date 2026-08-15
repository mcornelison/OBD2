from=Atlas(Architect); to=Marcus(PM); date=2026-08-15; topic=Pi static IP LANDED -- move deploy/sync off the flapping IP to the hostname (F-102/B-102); audience=agent; urgency=medium; refs=F-102,A-15,deploy/addresses.sh

CIO-directed: pinned the Pi to static IPs + verified. The flapping (.100/.9/.28) is dead. This unblocks the repo-side of F-102 (hostname resolution) -- the payoff.

## DONE (live on the Pi, CIO-directed)
- **wlan0 (WiFi) = 10.27.27.124** static (netplan boot config, persisted + reboot-verified). **eth0 = 10.27.27.123** static (stored, activates when cabled -- eth0 currently down).
- Gateway 10.27.27.1, DNS 10.27.27.120 + 1.1.1.1.
- **mDNS live: `chi-eclips-01.local` -> .124** (avahi active). Hostname access works NOW, no router change.
- Reboot clean: eclipse-obd/dashboard/states-http all active.
- Router-side reservation/DNS is the CIO's (I can't touch the router); MACs for a reservation: eth `88:a2:9e:84:46:1b`->.123, wlan `88:a2:9e:84:46:1c`->.124.

## REPO-SIDE FOLLOW-ON (F-102 -- route to Ralph)
1. **Move `PI_HOST` off the raw IP to the hostname.** Central def is `deploy/addresses.sh:18/30` (PI_HOST). Point deploy/sync/SSH at **`chi-eclips-01.local`** (stable) instead of a flapping IP. This is exactly what B-102/F-102 was for.
2. **HOSTNAME SPELLING BUG (verify-before-asserting catch):** `deploy/addresses.sh` + `deploy/deploy-pi.sh:3` + `deploy/boot-progress-arm.service:33` use **`chi-eclipse-01`** (with an 'e'). The Pi's ACTUAL hostname is **`chi-eclips-01`** (no 'e' -- "eclips"). `chi-eclipse-01.local` will NOT resolve. Reconcile to `chi-eclips-01` before switching deploy to the name, or it silently fails to the wrong host.
3. **Shared memory** MEMORY.md still says "Address FLAPS .100/.9/.28 -- probe all three" + "LIVE @ .100" -- now stale. Update to: static wlan0 `.124` / eth0 `.123` / mDNS `chi-eclips-01.local` (your/CIO's lane to edit shared memory).
4. Caveat (A-15 family): if any sync/offline-probe path is IP-route-based, confirm it still works when the target is a hostname (mDNS resolves, but check the offline-detection logic doesn't assume a numeric IP).

No architecture gate needed -- it's a config/deploy move. Flagging the spelling bug because it'll bite silently. -- Atlas
