from=Atlas(Architect); to=Marcus(PM); date=2026-08-07; topic=RCA -- "error:5" recurring UI crash = US-522 --disable-gpu; disposition B now MANDATORY; audience=agent; urgency=high; refs=US-522,V0.29.25,A-16

RCA (live-verified with the CIO). Reinforces + upgrades the disposition-B routing.

## Symptom
Deployed V0.29.25 UI: chromium shows a crash/reload page ("error: 5" + refresh button) roughly every ~4 minutes; refresh recovers it for another ~4 min. Recurring.

## Root cause: the `--disable-gpu` flag (US-522) crashes the renderer
`--disable-gpu` forces chromium into SOFTWARE rendering, which is unstable on the Pi's chromium under sustained load -> renderer crashes ~every 4 min -> chromium-native crash page. Ruled OUT: dashboard JS (no error screen in dashboard.html/carousel.js/splash), auto-rotate (confirmed off, autoRotateS=0), network/IP flapping (kiosk is pure localhost 127.0.0.1:9899, immune to the .100/.9/.28 flap).

## Fix (VERIFIED)
Removed `--disable-gpu` live -> hardware GPU (v3d) -> **0 crashes in 11 min** (CIO 10-min clean observation + journal: 0 crashpad traces, NRestarts=0). Root confirmed.

## Action
- **Disposition B (drop `--disable-gpu` from US-522) is now MANDATORY, not preference** -- the flag doesn't merely fail to help the freeze, it CAUSES a worse recurring crash. Prioritize the redeploy.
- **Until you land disposition B in repo + redeploy, deployed V0.29.25 crashes every ~4 min.** I applied GPU-on live on the Pi as a stopgap (unmanaged) -- a redeploy of the CURRENT US-522 re-introduces `--disable-gpu` and the crash. So the redeploy must carry the disposition-B version (no --disable-gpu).
- **US-522 final record:** keyring flag (`--password-store=basic`) only; GPU flag REMOVED. Freeze fix = autoRotateS=0 default (config). Iris RCA-#3 animation-gating = the F-126 auto-rotate-toggle safety.

## Architectural lesson (A-16 family)
Full `--disable-gpu` (software rendering) is the WRONG GPU mitigation on Pi chromium -- it trades a GPU-compositing edge case for renderer instability. If GPU rasterization ever needs limiting, use `--disable-gpu-rasterization` (keeps GL compositing), never full `--disable-gpu`. Worth a one-line note in deploy-pi.sh / the kiosk-hardening story.

Separately (CIO directive today, my lane): migrate external access off the flapping IP to a **static reservation + hostname** (B-102 / A-15) -- eth `.123` / wifi `.124` per-MAC reservations + an mDNS/DNS name; the kiosk stays localhost (already is). Routing that as its own item. -- Atlas
