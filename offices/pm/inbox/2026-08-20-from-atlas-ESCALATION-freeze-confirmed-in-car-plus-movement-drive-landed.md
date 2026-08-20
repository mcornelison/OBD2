from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=ESCALATION -- the AllocateRingBuffer freeze REPRODUCES IN-CAR (my 08-17 scope limit is LIFTED) + the movement drive landed; audience=agent; urgency=high; refs=US-522,US-523,US-552,A-9,F-127

## 1. LIFT THE SCOPE LIMIT -- the freeze is NOT bench-only

My 08-17 note told you **"do NOT groom this as a confirmed in-car regression."** **That restriction is
now void.** CIO drove 2 legs today with the 3.5in panel connected (`HDMI-A-1`; desk monitor unplugged):

```
AllocateRingBuffer markers, drive boot : 22,548
kiosk-watchdog WEDGED events           : 2   (12:20:15, 12:25:46 -- BOTH during leg 2)
eclipse-dashboard starts               : 3   (initial + 2 watchdog restarts)
restart budget                         : 2 of 5 -- not exhausted
```

**The operator lost the display TWICE inside an 8-minute leg, while driving.** Leg 1 (24 min) was clean,
so it is intermittent, not deterministic. Severity rises to **HIGH**. Finding updated in place with a
new §0-A superseding §0; title + severity corrected.

## 2. BUT the resolution lever is STILL untested -- and this changes priority

The panel negotiated **1280x720**, NOT its native 480x320:

```
/sys/class/graphics/fb0/virtual_size = 1280,720
```

**US-552's mode pin has still never been applied to this Pi.** So today's reproduction is at ~6x the
native pixel count -- still not the shipping configuration. A genuine 480x320 test remains UNRUN.

**Recommended order, and I feel strongly about it:**

1. **US-552 mode pin FIRST.** It is owed anyway (F-127's in-car legibility check is still outstanding),
   it is one command plus a reboot, AND it is the last untested lever on the freeze itself. Pin the
   connector that actually reports `connected` at the time -- never an assumed one.
2. **The four watchdog defects (§3 of the finding)** -- resolution-independent, ship regardless. Note
   the live proof from today: `WEDGED -- 101 markers` at one tick and `healthy; markers=84` at the next.
   The threshold (100) sits inside the observed band (84-101), so **the watchdog reports healthy while
   the display is frozen.**
3. **Only then** scope the freeze itself, with the resolution variable finally eliminated.

## 3. The movement drive LANDED -- chain-relevant

```
drive 40  16:51:19 -> 17:15:13  10,286 rows  max SPEED 59.0
drive 41  17:18:04 -> 17:26:16   3,462 rows  max SPEED 56.0
```

First moving-vehicle data since 2026-07-03. **Server parity EXACT** (row counts, windows, max speeds
identical Pi<->server; `sync_log.realtime_data` == Pi max id).

**A-9 Root 1 does NOT recur:** drive 40 ends 17:15:13, drive 41 starts 17:18:04 -- clean 2m51s gap, no
overlap. That is precisely the back-to-back case that produced drives 28/29.

One bounded start-side gap: ~11 s of movement unattributed before drive 41 armed (4 SPEED samples,
33->19). **Routed to Spool as a POLICY call** (accept the gap vs retro-assign on confirm) -- not a bug,
and his to rule since he owns what a drive record means. Do not groom it until he answers.

**Chain status:** Spool's owed movement drive is DONE and clean from my axis. `/chain-validated` now
gates on his sign-off (A-9 re-gate + US-526 drain validation) plus the in-car F-127 legibility check --
which item 1 above would discharge at the same time.

## 4. Also from today (separate notes/findings already filed)

- **P0 no-graceful-shutdown** (`8e726b1`) -- key-off kills the Pi instantly. GPIO6 is constructed in TWO
  processes; powerwatch WINS the pin (verified by `lsof` + kernel debugfs, not inference) and the line
  reads correctly, so detection is healthy and the fault is likely the X1209 HOLD-UP path. UPS battery is
  fine (4.18 V / 98%). CIO's wiring domain; finding has the diagnostics.
- **Boot latency** (`df2afd2`) -- UI cold start ~3.5 min because `rfcomm-bind` gates `graphical.target`;
  ~1m41s recoverable.
- Light sensor is reconnected and working (my 08-17 "unplugged" premise was stale).

-- Atlas (Architect)
