# Gap — UI cold-start is ~3.5 min because the DISPLAY is gated behind the BLUETOOTH/OBD tier

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Reported by:** CIO — "~2 min before the UI turned on after the Pi was up, then another 30-60 s before
all the data became visible. Note it for optimization later."
**Measured on:** live Pi `10.27.27.124`, V0.29.29, boot 2026-08-20 10:32:06.
**Severity:** Low (no defect — everything works), but a large, cheap win and an ARCHITECTURAL
inconsistency with a ruling already on the books.

---

## Measured breakdown (monotonic — see §4 for why wall-clock is unusable here)

```
systemd-analyze: 2.998s (kernel) + 3min 3.872s (userspace) = 3min 6.871s
graphical.target        @ 1min 47.576s     <- display stack READY
eclipse-dashboard       @ 3min 28.621s     <- browser actually launches
                          ~~~~~~~~~~~~~~
                          1min 41s of dead time with a ready display stack
```

Critical chain into the UI:

```
eclipse-dashboard.service @3min 28.621s
`-graphical.target @1min 47.576s
  `-multi-user.target @1min 47.576s
    `-rfcomm-bind.service @1min 47.538s +37ms      <- BLUETOOTH gates multi-user
      `-eclipse-rfkill-unblock.service @5.407s
```

Slowest units:

```
1min 42.086s  eclipse-bond-selfheal.service     <- US-545 BT bond self-heal
1min 16.331s  orphan-cleanup.service
    5.970s    NetworkManager-wait-online.service
```

## The architectural point

**`rfcomm-bind.service` sits in the critical chain to `multi-user.target` -> `graphical.target`.** So the
operator's DISPLAY does not appear until the BLUETOOTH/OBD tier has settled, and `eclipse-bond-selfheal`
alone costs **1 min 42 s**.

This is the same error I ruled on for the splash in the 2026-07-28 UI SSOT-wiring design
(`docs/superpowers/specs/2026-07-28-pi-ui-carousel-ssot-wiring-design.md`): **the display must hand off on
PI-CORE-UP, never on VEHICLE-UP.** There it was `boot_state_emitter`'s `obdProbeFn` stub pinning the
splash at "not ready (starting)" forever. Same principle, different mechanism: the Pi-local UI is
waiting on a vehicle-tier dependency it does not need in order to paint.

Nothing on the dashboard's first frame requires Bluetooth. The honest-availability card model exists
precisely so the UI can render immediately with typed-NA cards and fill in as sources arrive.

## The CIO's second observation (+30-60 s to data) is DIFFERENT and mostly correct-by-design

That window is the OBD connect handshake plus the first poll cycles. It is the honest-availability model
working: cards render `unavailable`/NA and populate as each source lands. Some of it is reducible (first
poll cadence), but unlike the 1m41s above it is not dead time -- do NOT optimize it by delaying the UI
until data is ready, which would be the same mistake inverted.

## Suggested direction (design work owed to Atlas before this is groomed)

1. **Take `rfcomm-bind` out of the critical path to `graphical.target`.** The BT/OBD tier should
   converge asynchronously; the kiosk should depend on `eclipse-states-http` being up, not on the
   vehicle link.
2. **`eclipse-bond-selfheal` (1m42s) should not block boot.** It is a recovery path -- run it
   `Type=simple`/backgrounded or on a timer, not as a boot-ordering dependency.
3. **`orphan-cleanup` (1m16s)** -- audit whether it must be synchronous at boot.
4. Re-measure with `systemd-analyze critical-chain` after each change; the target is UI painting shortly
   after `graphical.target` (~1m48s), i.e. roughly **halving cold start**.

Expected win: **~1m40s off time-to-first-pixel**, with no change to what is eventually displayed.

## 4. Bonus finding — F-3 (clock trust) confirmed empirically on this boot

`systemctl show <unit> -p ActiveEnterTimestamp` reports **Mon 2026-08-17 17:07:31** for
`eclipse-states-http` and `eclipse-boot-state` -- **three days BEFORE this boot** -- while both are
active right now (PIDs 741 / 739, `:9899` listening). Later services (`eclipse-obd` PID 2671,
`eclipse-dashboard` PID 3823) carry correct times.

Those two are the EARLIEST-starting units, stamped **before systemd-timesyncd disciplined the clock**.
`timedatectl` now reports `NTPSynchronized: yes`.

**This is exactly the failure mode `src/pi/diagnostics/clock_sync.py` exists to guard and that F-3 says
the UI ignores** (finding `2026-08-17-ui-ssot-audit-five-unbacked-facts.md` §F-3): the Pi boots with an
untrustworthy clock, anything stamped in that window carries a wrong time, and the top-bar clock renders
`new Date()` with no NA path. It is no longer hypothetical -- **this boot produced three-day-stale
timestamps on live services.**

**Practical corollary for anyone doing boot analysis on this Pi: use monotonic time
(`systemd-analyze`), never `ActiveEnterTimestamp`.**
