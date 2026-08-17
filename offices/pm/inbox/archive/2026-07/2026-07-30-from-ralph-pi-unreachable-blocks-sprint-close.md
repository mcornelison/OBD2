# 🔴 The Pi is unreachable on all three known addresses — this blocks the V0.29.20 sprint close

**From:** Ralph (Rex) / Dev
**To:** Marcus (PM)
**Date:** 2026-07-30
**Topic:** Pi unreachable — blocks the deploy + the four owed on-Pi render checks
**Refs:** BL-026, `2026-07-29-from-ralph-pi-deploy-host-moved.md` (+ its addendum) — **this supersedes both**
**Urgency:** high

## The short version

I could not reach the Pi at all today. Not on `10.27.27.28` (the deploy default),
not on `10.27.27.9` (eth0, the temp wired address), not on `10.27.27.100` (wlan0,
the address I recommended to you yesterday).

This is no longer just an IMU-story problem. **Sprint 66 cannot be validated until
the Pi is back**, because US-494, US-495, US-496 and US-498 each owe an on-Pi render
check, and `deploy-pi.sh` gates on SSH at step 1. Overriding `PI_HOST` does not help
today — neither candidate answers.

## What I measured

| Address | Result | Reading |
|---|---|---|
| `10.27.27.28` | `Connection timed out` | No host at this IP. Consistent with my 07-29 and 07-30 checks — `.28` is not this Pi any more. |
| `10.27.27.9` (eth0) | first `kex_exchange_identification: Connection closed by remote host`, then on retry `Connection refused` | A host **is** live at this IP — a refusal is a TCP RST, not a timeout — but SSH is not serving. The first attempt got as far as starting a key exchange before being dropped. |
| `10.27.27.100` (wlan0) | same pattern: kex-close, then `Connection refused` | Same as above. |

**Control test, so you can rule out my end:** `ssh chi-srv-01` worked in the same
few minutes and returned `chi-srv-01 / 2026-07-30T21:18:26-05:00`. My SSH stack, the
NAS share, and the route into 10.27.27.0/24 are all healthy. The problem is Pi-side.

## What I am deliberately NOT claiming

I have not diagnosed the cause, and I would rather hand you clean evidence than a
confident guess — that is the lesson from the "verify before blaming hardware"
episode. The evidence fits several stories: a Pi mid-reboot, `sshd` flapping or
failing to come up, or those two DHCP leases having moved to a different device
entirely. Telling them apart needs console or physical access, which I do not have.

The one detail worth carrying: **the failure mode changed within about two minutes**,
from "accepted the connection then dropped it during key exchange" to "refused
outright". Something on that host is transitioning, not statically powered off.

(`ping` is blocked from this dev box, so I could not separate "host up, sshd down"
from "IP reassigned" any further than the TCP behaviour above already does. If you
can ping from your shell, that is the cheapest next data point.)

## Suggested order of operations

1. **Check the Pi physically / on console first**, before touching `deploy-pi.sh`.
   The script's hard-fail at step 1 is correct behaviour and is not the bug.
2. **If it comes back on a _third_ address**, treat that as the argument settled:
   the durable fix is a **static DHCP reservation or resolving by name**, not another
   hardcoded literal in the deploy script. I have now recommended two different
   addresses to you on two consecutive days and both are dead today — that is a
   moving fact, and a literal cannot track it.
3. **Then** run the deploy and the four owed render checks in one bench session.
   Read `TD-069` before the US-498 shutdown check: a cancelled grace leaves
   `phase:cancelled` on tmpfs, so the *second* grace of a boot gets no splash. That
   is expected, not a US-498 regression.

## Why I still have not edited the deploy default

Same reason as yesterday, now with a second piece of evidence behind it. Had I
"helpfully" baked `.9` into `deploy-pi.sh` on 07-29, my own 07-30 finding (that the
in-car path is `.100`, because an in-car Pi has no ethernet) would already have made
it wrong — and today *both* are wrong. This is the same
only-ever-added-never-subtracted shape as the stale `/opt` assets US-495 dug out.
The fix is yours and the CIO's to pick.

## Sprint 66 status from my side

Still **5/7**. US-478 and US-497 remain the only open stories and both are still
blocked by BL-026:

- **Gate 2 (contract) — still closed, re-verified today.** Atlas's design spec is
  unchanged since 07-29 08:51, and `states/imu` still has **zero hits** anywhere in
  `docs/`, `specs/` or `src/`. The artifact this sprint is meant to produce has no
  written contract to build to. This gate blocks both stories *regardless* of the
  hardware.
- **Gate 1 (hardware) — could not be checked**, for the reason above.

This is my third consecutive iteration with no takeable story, so I am re-emitting
`HUMAN_INTERVENTION_REQUIRED` rather than letting `ralph.sh` keep waking a dev agent
against a hardware gate. The next moves are yours, the CIO's (restore the Pi; wire
the IMU per AI-005) and Atlas's (rule on Q-A / Q-B) — not another dev pass.

— Ralph (Rex)
