# F-117: OBD capture broken — eclipse-obd connection-thread race (0 rows captured)

| Field | Value |
|---|---|
| Priority | **P0** (the Pi captures ZERO OBD rows until this lands — the core loop is down) |
| Status | pending |
| Category | data-capture / concurrency |
| Size | M/L |
| Parent Epic | E-OPS — Operational Reliability |
| Related | BL-016 (US-432 idle-poll — likely a SYMPTOM of this; re-examine after), TD-036/US-244 (timeout daemons), US-301 (heartbeat connect path), f389d5b (crash-loop hotfix, deployed V0.29.7) |
| Created | 2026-07-03 |
| Source | Atlas RCA `offices/architect/findings/2026-07-03-obd-capture-rca-eclipse-obd-connection-thread-race.md` (CIO-directed live car debug) |

## Description

**The Pi captures 0 OBD rows.** Atlas's CIO-directed live debug (car running) ran the tree to the bottom. **Decisive test:** with `eclipse-obd` STOPPED, raw `python-obd` on the same port/params reads RPM flawlessly (5/5, ISO 9141-2) — so dongle/ECU/K-line/pairing are ALL good. The **only** thing that fails is eclipse-obd's own connection wrapper: connect → first read returns empty → "Device disconnected while reading" → 0 rows, every connect.

**Root cause (concurrency):** `python-obd`'s connection is NOT thread-safe. eclipse-obd runs connect+query on **timeout-bounded daemon threads left running on timeout** (TD-036/US-244 anti-boot-hang) plus a second connect path (US-301 heartbeat). Orphaned timeout-daemons touch the one shared `self._connection.obd` concurrently with the realtime logger → serial I/O interleaves → empty read. Standalone = 1 thread = works. (`lifecycle.py:760-885, 921-965`.)

## Acceptance Criteria (fix direction per the RCA)

- [ ] **Serialize ALL `self._connection` access behind one lock** — no two threads touch the python-obd connection concurrently.
- [ ] **Fence orphaned timeout daemons** — a timed-out connect/query thread is BARRED from touching a connection a later thread owns (generation/ownership token or equivalent).
- [ ] **Preserve the TD-036 no-boot-hang property** — the anti-boot-hang timeout behavior must not regress.
- [ ] Verify with **thread-named instrumentation** + a **live sustained-capture drive** (rows actually accumulate on the car) — the existing tests mock the connection and are green while the live path captures nothing (mocked-green/IRL-miss class).
- [ ] `ruff check` passes.

## Cross-references

| Item | Relationship |
|---|---|
| f389d5b | Crash-loop hotfix (None.close → ADAPTER_UNREACHABLE, was FATAL) — DEPLOYED in V0.29.7; stops the crash, NOT the capture fix |
| BL-016 / US-432 | Idle-poll RPM-mask — likely a symptom of this thread-race (empty reads); **re-examine BL-016 AFTER this lands** — may resolve or be a real secondary |
| Chain validation | The whole V0.29 chain's on-Pi capture is broken until this lands — a hard gate for any capture-dependent validation |

## Notes

Atlas: "Hardware/pairing/crash all cleared — don't let anyone re-chase those." This is **the Sprint 54 P0.**
