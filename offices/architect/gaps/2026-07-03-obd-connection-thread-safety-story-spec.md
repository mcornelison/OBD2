# Story spec — Make eclipse-obd's OBD connection access thread-safe (fix the capture-killing race)

**Author:** Atlas (architect) · **Date:** 2026-07-03 · **For:** Marcus to groom → Ralph to build.
**Priority:** HIGH — the Pi captures **zero** OBD rows until this lands.
**RCA (read first):** `offices/architect/findings/2026-07-03-obd-capture-rca-eclipse-obd-connection-thread-race.md`
**Related:** hotfix `f389d5b` (crash-loop; already on `sprint/sprint53-V0.29.7`) is a *separate* fix — it stops the
crash but NOT the capture failure. This story is the capture fix.

## Problem (one paragraph)
`python-obd`'s connection object wraps one serial port and is **not thread-safe**. eclipse-obd's connection
lifecycle runs connect and query on **timeout-bounded daemon threads that are left running on timeout**
(TD-036/US-244, anti-boot-hang) and adds a **second** connect path (US-301 reconnect heartbeat). When an orphaned
timeout-daemon (a left-running `_connectInThread` or `_queryInThread`) or the heartbeat touches
`self._connection.obd` at the same instant the realtime logger reads, the ELM327 responses interleave → the
logger's read returns empty → `obd.elm327 __read | Device disconnected while reading` → 0 rows, every connect.
Proven: with eclipse-obd stopped, raw single-threaded `python-obd` on the same port reads RPM flawlessly (5/5).

## Scope of change (`src/pi/obdii/orchestrator/lifecycle.py` + connection wrapper)
1. **Single serialization lock for ALL connection I/O.** Introduce one lock (e.g. `self._connLock`) held around
   every access to `self._connection` / `self._connection.obd`: `connect()`, every `query()`, the reconnect
   probe, and the heartbeat `connectFn`. No two threads may drive the serial port concurrently.
2. **Epoch/generation fence for orphaned timeout daemons.** Each connect/query attempt gets a monotonically
   increasing epoch stamped at spawn. A daemon thread MUST re-check "am I still the current epoch?" under the
   lock immediately before touching `self._connection`, and abort + discard its result if superseded. A
   timed-out `_connectInThread`/`_queryInThread` that later wakes must NOT mutate or read a connection a newer
   owner now holds.
3. **Name the threads.** `threading.Thread(name="obd-connect-<epoch>"/"obd-query-<param>"/"obd-reconnect-hb")`
   so orphans are visible in `ps -T` and logs (they're currently all "python" — undiagnosable). Low effort,
   high future-debugging value.
4. **Preserve the TD-036 no-boot-hang property.** Do NOT reintroduce a forever-blocking connect on boot — bound
   lock acquisition on the boot path (or keep the daemon-launch shape and gate *access* via epoch+lock rather
   than serializing the *spawn*). The point of the daemon pattern (never hang boot) must survive.

## Acceptance criteria / DoD
- [ ] All `self._connection`/`.obd` access is under `self._connLock`; verified by code inspection + a unit test
      that spins concurrent connect+query threads against a mock connection and asserts **no interleaving**.
- [ ] Epoch fence unit test: a superseded (timed-out) daemon's late `connect()`/`query()` is dropped and cannot
      corrupt the current connection's state.
- [ ] Threads are named; `ps -T -p <pid>` shows meaningful names.
- [ ] Boot path still cannot hang (TD-036 regression test / bounded-acquire proven).
- [ ] **LIVE acceptance gate (IRL, needs the car — the real proof):** on the Pi with the engine running,
      eclipse-obd connects and captures **sustained `realtime_data` rows (RPM + params) for ≥60 s with ZERO
      self-inflicted "device disconnected while reading"**, `drive_start` fires, and rows sync to chi-srv-01.
      This must match the clean behavior the standalone `python-obd` probe already demonstrated.
- [ ] `ruff` + `mypy` clean; `regression_manifest.json` updated.
- [ ] **Rule-10:** update the connection-lifecycle section of `specs/architecture.md` in-sprint (load-bearing
      subsystem — threading model of the OBD connection).

## Out of scope
- python-obd's internal `None.close` bug — already mitigated by the classifier hotfix `f389d5b` (do not patch the
  venv library; a future story may pin/upgrade python-obd).
- Bluetooth pairing, dongle, ECU, K-line — all verified healthy this session; not part of this fix.
- Server sync — verified healthy (rowsPushed>0, `.120` reachable).

## Verification notes for the builder
- The definitive baseline is: `sudo /home/mcornelison/obd2-venv/bin/python -c "..."` running `obd.OBD(...)` +
  `query(RPM)` in a single thread → clean reads. Your fix must make eclipse-obd behave identically.
- Reproduce the failure by watching the journal on connect: pre-fix you get "Realtime logging started" →
  "Device disconnected while reading" within ~1 s. Post-fix that must be gone under sustained load.

— Atlas
