# [CLOSED 2026-07-21 — Atlas applied the §3.5 edit, committed `45a54d1`] I: specs/architecture.md §3.5 — add the DTC read path + US-474 contract test

> **RESOLVED.** Atlas (owns architecture.md) applied the requested §3.5 edits: added the DTC read/clear paths (`DtcClient` Mode 03/07/04 + US-404 KOEO connect-edge) to the "every caller goes through the wrapper" list, noted the typed `ObdConnectionLike.query()` closes the raw-bypass hole (US-474), and referenced `tests/pi/obdii/test_dtc_connect_edge_concurrency.py`. Not a Ralph story (specs/ read-only). No further action.

- **Found by:** Rex (Ralph agent), Sprint 60 / US-474, 2026-07-20
- **Type:** load-bearing spec update owed in-sprint (design-gate DoD / PM Rule 10)
- **Why filed as an issue:** `specs/` is read-only for Ralph (prompt.md) — same
  handoff pattern as US-462/464/467/468/469. Please apply (or route to Atlas).

## Context

US-474 hardened the F-117/A-17 connection-lock subsystem: it removed the runtime
`getattr(connection, 'query', None)` fallback in
`src/pi/obdii/dtc_client.py::_serializedQuery` (the last raw unlocked
`.obd.query` path) and made `query()` a **typed member** of the
`ObdConnectionLike` Protocol, so every DTC read provably shares the single
`ObdConnection._ioLock`.

`specs/architecture.md` §3.5 ("OBD Connection Threading Model — serialization +
epoch fence") already documents the lock model, BUT its "Every caller goes
through the wrapper" paragraph enumerates only the realtime logger
(`logger.py`). The **DTC read paths were the exact A-17 caller** that bypassed
the lock via raw `.obd.query()`, and they are now closed — the spec should say
so, and reference the new regression test.

## Requested edits to §3.5 (specs/architecture.md, ~lines 491–531)

1. In the "Every caller goes through the wrapper" paragraph, add the DTC reads
   to the caller list, e.g.:
   > … the realtime logger's reads (`logger.py`) **and the DTC read paths
   > (`DtcClient` — Mode 03 / 07 / 04, incl. the US-404 KOEO connect-edge read)
   > — all call `connection.query()`, never raw `connection.obd.query()`
   > (US-474 removed the last `getattr`-based raw fallback).**

2. In the `query` row of the access table (or a note): mention the typed
   `ObdConnectionLike.query()` contract closes the raw-bypass hole (US-474).

3. Under "Contract test", add the new non-mocked connect-edge regression:
   `tests/pi/obdii/test_dtc_connect_edge_concurrency.py`
   (real ObdConnection + real DtcClient; a logger read + a KOEO DTC read
   serialize through `_ioLock` on one faked non-thread-safe port; reverting the
   lock makes it RED). This is the guard for F-117 GAP-1.

No code/behavior change requested here — the spec already describes the
invariant; this just makes the DTC caller + the new test explicit so §3.5
matches the shipped US-474 contract.
