# Pi is up but NOT at its deploy address — `deploy-pi.sh` will hard-fail as configured

**From:** Ralph (Rex) — **To:** Marcus (PM) — **Date:** 2026-07-29 — **Re:** Sprint 66 (V0.29.20) on-Pi validation

Short note, routed because your next move on this sprint is a deploy + bench
session and it will stop at step 1 if you run it as-is.

## What I found

Checking the I²C bus for BL-026 (see that file — the IMU is still not wired), the
Pi did not answer on its deploy address:

- `ssh chi-eclipse-01` → **`10.27.27.28` connection timed out**
- `ssh mcornelison@10.27.27.9` → **answers fine**, `i2cdetect` ran normally

`10.27.27.9` is the temp **wired** address from the WiFi rebuild. So the Pi is
healthy and reachable; it has just moved.

## Why it matters to you specifically

`deploy/deploy-pi.sh` defaults `PI_HOST=10.27.27.28` (line 14) and its **step 1 is
an SSH gate** that aborts before touching anything. That is correct behaviour —
loud failure, nothing half-shipped — but it means:

```bash
PI_HOST=10.27.27.9 bash deploy/deploy-pi.sh
```

is what actually deploys today. Worth confirming the address is still current when
you run it; if the Pi has been put back on WiFi by then, the default is right again.

**I did not change the default.** The address is transient, and baking a temporary
one into the deploy script is precisely how a stale address becomes permanent —
the same "only ever added, never subtracted" shape as the stale `/opt` assets
US-495 dug out. If the CIO decides the wired address is the new normal, that is a
config change with an owner, not a drive-by edit from a blocked iteration.

## The thing this unblocks

Four stories owe an on-Pi render check and none of them can be discharged from my
box: **US-494** (bench boot reaches the dashboard), **US-495** (no overlay paints
at idle + read the deploy's new `pruned stale asset` lines — those are the
diagnosis of the 25-day stale-surface mystery, capture them before they scroll),
**US-496** (swipe the carousel; **count the page dots** against the visible cards),
**US-498** (trigger a real grace and **watch the first two seconds** — that is
where the black-screen bug lived).

US-499's backstop discharges itself automatically and covers "does this element
have a box". It does **not** cover "does it look right and does the motion feel
right". That is still one bench session.

## Sprint state

5/7. US-478 + US-497 remain, both blocked by BL-026 — re-verified today against
the live bus (no `0x69`) and against Atlas's design spec (no Q-A/Q-B ruling), not
just re-read. There is no further dev work I can pick up in Sprint 66.

— Rex
