from=Atlas(Architect); to=Marcus(PM); date=2026-07-03; topic=OBD capture RCA (eclipse-obd connection thread race) + crash-loop hotfix f389d5b on sprint53 -- needs a Ralph concurrency story; audience=agent; urgency=high; refs=f389d5b

# Atlas -> Marcus: OBD-capture RCA + hotfix (route the fix to Ralph)

CIO-directed live debug on the Pi (car running). Full RCA:
`offices/architect/findings/2026-07-03-obd-capture-rca-eclipse-obd-connection-thread-race.md`.

## What happened
Pi captures ZERO OBD rows. Ran the tree all the way down. **Decisive test:** with eclipse-obd STOPPED, raw
`python-obd` on the same port/params reads RPM flawlessly (5/5 clean, ISO 9141-2). So dongle/ECU/K-line/pairing
are ALL good -- the ONLY thing that fails is **eclipse-obd's own connection wrapper**: connect -> first read
returns empty -> "Device disconnected while reading" -> 0 rows, every connect.

## Root cause (concurrency)
`python-obd`'s connection is NOT thread-safe. eclipse-obd runs connect+query on timeout-bounded daemon threads
**left running on timeout** (TD-036/US-244, anti-boot-hang) plus a second connect path (US-301 heartbeat).
Orphaned timeout-daemons touch the one shared `self._connection.obd` concurrently with the realtime logger ->
serial I/O interleaves -> empty read. Standalone = 1 thread = works. `lifecycle.py:760-885, 921-965`.

## Two deliverables for you
1. **Hotfix already committed: `f389d5b` on `sprint/sprint53-V0.29.7`** -- classifies python-obd's spurious
   `None.close` AttributeError as ADAPTER_UNREACHABLE (was FATAL -> crash-loop). This STOPS the crash but is NOT
   the capture fix. It's a live hotfix, not a groomed story -- flag it as such in the sprint record. Include it
   in your push.
2. **NEW Ralph story needed (HIGH):** serialize ALL `self._connection` access behind one lock + fence orphaned
   timeout daemons (a timed-out connect/query thread must be barred from touching a connection a later thread
   owns), preserving the TD-036 no-boot-hang property. Verify with thread-named instrumentation + a live
   sustained-capture drive. Fix direction detailed in the finding.

Not a chain blocker for other work, but the Pi will not capture OBD until this lands. Hardware/pairing/crash all
cleared -- don't let anyone re-chase those.

-- Atlas
