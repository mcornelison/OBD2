# RCA — OBD capture failure is an eclipse-obd connection-lifecycle thread race (NOT python-obd / dongle / ECU / Bluetooth)

**By:** Atlas · **Date:** 2026-07-03 · **Root-caused live on the Pi (car running).**
**Severity:** HIGH — the Pi captures **zero** OBD rows despite a fully healthy dongle/ECU/pairing.
**Related:** hotfix `f389d5b` (crash-loop) — this RCA is the *underlying* read-failure that the crash masked.

## The one decisive experiment
With **eclipse-obd stopped**, a raw `python-obd` session on the exact same port/params eclipse-obd uses
(`obd.OBD("/dev/rfcomm0", fast=False, timeout=...)`) connected and read RPM **flawlessly**:

```
STATUS: Car Connected | PROTOCOL: ISO 9141-2
QUERY[0] RPM=780.0  [1] 756.0  [2] 728.0  [3] 744.0  [4] 752.0   (5/5 clean, valid 48 6B 00 41 0C.. frames)
```

So **python-obd + OBDLink LX + ECU + K-line + Bluetooth pairing are ALL good.** The *only* component that fails
is **eclipse-obd's own connection wrapper**: it connects, then the very first realtime read returns empty →
`CRITICAL obd.elm327 __read | Device disconnected while reading` → 0 rows, every single connect.

## Root cause: concurrent access to the single, non-thread-safe python-obd connection
`python-obd`'s connection wraps one serial port and is **not thread-safe**. eclipse-obd's connection lifecycle
runs connect/query on **timeout-bounded daemon threads that are deliberately LEFT RUNNING on timeout**
(TD-036 / US-244, added to avoid boot hangs — `orchestrator/lifecycle.py`):

- `_initializeConnection` → `_connectInThread`: "On timeout, the daemon thread is left running -- it may
  eventually [connect]" (`lifecycle.py:760-794`, log: *"PENDING (connect daemon thread continues)"*).
- `_queryInThread`: "On timeout, the daemon thread is left running -- it may eventually return"
  (`lifecycle.py:845-885`).
- `_spawnReconnectHeartbeatDaemon` (US-301): a **second** connect path firing `connectFn` on its own daemon
  (`lifecycle.py:921-965`).

Net: when the reconnect heartbeat (or a returning initial-connect daemon) establishes the connection and the
realtime logger starts reading, one or more **orphaned timeout-daemon threads** (a left-running connect, or a
left-running query) are still holding/touching `self._connection.obd` → two threads drive the one serial port
→ ELM327 responses interleave → the logger's read comes back empty → "Device disconnected while reading."
The standalone test has exactly **one** thread → no race → clean reads. This is the whole delta.

## Why "it worked before"
The race is timing-dependent (needs a slow/timed-out connect to leave an orphan running at the moment the
logger reads). The 30s connect timeouts we're seeing now (marginal first-connect on the slow ISO 9141-2 K-line)
make the orphan-overlap window wide open every time. On a fast clean first-connect the orphan may exit before
the logger reads, so capture "worked" intermittently in the past. The bug is latent-but-real, not a fresh
regression in the connection code itself (git confirms `obd_connection.py`/`reconnect_loop.py` unchanged since
May; `python-obd` 3.5/0.7.3 unchanged since April).

## Fix direction (dev / Ralph — this is a concurrency redesign, not a one-liner)
1. **Serialize ALL access to `self._connection`** behind a single lock (connect, query, reconnect-probe,
   heartbeat connectFn) so no two threads ever drive the serial port concurrently. This is the core fix.
2. **Reconcile orphaned timeout daemons** before a new connect/read: a left-running `_connectInThread` /
   `_queryInThread` must be fenced (its result discarded and its access barred) once its bounding timeout has
   fired — it must NOT be allowed to touch a connection a later thread now owns.
3. Preserve the TD-036 no-boot-hang property (the reason the daemon pattern exists) — the lock + fence approach
   keeps that while removing the race.
4. **Verify** with thread-named instrumentation (set `threading.Thread(name=...)` so orphans are visible) +
   a live capture test: connect → sustained rows with no "disconnected while reading."

## Hardware/pairing status (all cleared this session — do NOT re-chase)
- OBDLink LX: healthy (reads 14.2V, ELM327 v1.4b, full standalone read). Was hung once; a reseat fixed it.
- Bluetooth pairing: was a stale-key auth failure (CIO's insight); **fixed** via dongle factory-reset + fresh SSP bond.
- Crash-loop on disconnect: **fixed** (`f389d5b`, classify python-obd's None.close artifact as ADAPTER_UNREACHABLE).
- ECU/K-line/phone: all confirmed good.

— Atlas
