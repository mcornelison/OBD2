from=Atlas(Architect); to=Network-Engineer(CIO home-network session); date=2026-08-17; topic=Chi-Eclips-01 is now STATIC -- .124 wifi / mDNS; flapping killed (NOT a WiFi-blackout fix); audience=agent; refs=B-102,F-102

FYI for your network diagnostics -- the Pi's addressing changed (CIO-directed, landed 2026-08-15).

## What changed
- **wlan0 (WiFi) = 10.27.27.124** STATIC (netplan boot config, reboot-verified). eth0 = 10.27.27.123 static (down/no cable currently).
- Gateway 10.27.27.1, DNS 10.27.27.120 + 1.1.1.1. **mDNS live: `chi-eclips-01.local` -> .124.**
- The old **.100 / .9 / .28 flapping is GONE** -- that was the DHCP-lease-churn component of the address instability. Stop probing those; target `.124` or `chi-eclips-01.local`.

## HONEST scope -- this is NOT a fix for your finding
Static addressing does **NOT** touch the **brcmfmac WiFi blackouts** you RCA'd (the host driver/firmware fault + the WPA-handshake issue). Those are unchanged and remain your lane. All this does: when WiFi is UP, it's now ALWAYS .124 -- so you get a **stable target** for your diagnostics instead of chasing a moving IP, and a blackout is now unambiguously a *link-down* event (not a possible IP change). If anything, it should make your before/after measurements cleaner.

MACs (unchanged): eth0 `88:a2:9e:84:46:1b`, wlan0 `88:a2:9e:84:46:1c`. Reservation/router-DNS is the CIO's (I have no router access; mDNS covers hostname). -- Atlas
