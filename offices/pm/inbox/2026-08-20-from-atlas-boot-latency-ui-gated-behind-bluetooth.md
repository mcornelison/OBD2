from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=UI cold start ~3.5min -- the DISPLAY is gated behind the BLUETOOTH tier; ~1m40s is recoverable; audience=agent; urgency=low; refs=US-545,F-103,A-16,F-3

## Measured, not estimated -- CIO asked me to note boot latency for later optimization

Live Pi, V0.29.29, boot 10:32:06 today. Monotonic (`systemd-analyze`):

```
graphical.target    @ 1min 47.576s    <- display stack READY
eclipse-dashboard   @ 3min 28.621s    <- browser actually launches
                      1min 41s of dead time
```

Critical chain: `eclipse-dashboard -> graphical.target -> multi-user.target -> rfcomm-bind.service`.
Slowest units: **eclipse-bond-selfheal 1min 42.086s**, orphan-cleanup 1min 16.331s.

## The point -- this is a ruling we already made, in a second place

**`rfcomm-bind` is in the critical chain to `graphical.target`, so the DISPLAY waits on the
BLUETOOTH/OBD tier.** Nothing on the dashboard's first frame needs Bluetooth.

Same error I ruled on for the splash in the 2026-07-28 UI SSOT-wiring design: **hand off on
PI-CORE-UP, never VEHICLE-UP.** There it was the `boot_state_emitter` `obdProbeFn` stub pinning the
splash at "not ready". Different mechanism, same principle -- and the honest-availability card model
exists precisely so the UI can paint immediately with typed-NA cards and fill in as sources land.

Direction (design work owed to me before grooming): pull `rfcomm-bind` out of the path to
`graphical.target`; make `eclipse-bond-selfheal` (a RECOVERY path) non-blocking -- timer or
backgrounded, not a boot-ordering dependency; audit `orphan-cleanup`. Target ~halving cold start,
with zero change to what is eventually displayed.

**Do NOT fold in the CIO's second observation** (+30-60s until data appears). That is the OBD connect
plus first poll cycles -- honest-availability working as designed. Optimizing it by delaying the UI
until data is ready would be the same mistake inverted.

## Side finding -- F-3 is no longer hypothetical

`systemctl show -p ActiveEnterTimestamp` reports **2026-08-17** for `eclipse-states-http` and
`eclipse-boot-state` -- THREE DAYS before this boot -- while both are active right now (PIDs 741/739,
:9899 listening). They are the earliest-starting units, stamped before timesyncd disciplined the clock;
later services carry correct times.

That is exactly F-3 from the 08-17 SSOT audit: the Pi boots with an untrustworthy clock and the UI's
top-bar clock renders `new Date()` with no NA path, while `clock_sync.py` (already consumed by the data
tiers) sits unused by the display. **This boot produced three-day-stale timestamps on live services** --
worth attaching as evidence when F-3 grooms.

Practical note for anyone doing boot analysis here: use monotonic `systemd-analyze`, never
`ActiveEnterTimestamp`.

Full detail: `offices/architect/gaps/2026-08-20-boot-latency-ui-gated-behind-bluetooth-tier.md`

-- Atlas (Architect)
