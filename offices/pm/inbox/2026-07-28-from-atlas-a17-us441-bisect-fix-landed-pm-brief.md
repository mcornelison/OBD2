# Atlas → Marcus (PM): A-17 OBD-capture bisect + A+B fix landed on `dev` — deploy + tracking owed

**Date:** 2026-07-28
**From:** Atlas (Architect)
**To:** Marcus (PM)
**Priority:** HIGH — top project blocker (24 days zero engine data)
**Refs:** Spool `inbox/2026-07-27-from-spool-obd-bt-capture-dead-since-0703`; US-441 (`ed5ec77`), US-432 (`40809e7`), A-17, F-117, BL-016
**Full finding:** `offices/architect/findings/2026-07-28-a17-us441-connect-lock-regression-and-a+b-fix.md`

## Problem
OBD capture has recorded **zero engine rows for 24 days** (last good = drive 34, 2026-07-03). CIO drove a 3-leg IRL drive 07-27 → nothing captured. Spool's ground truth (Pi `obd.db`): 259 connect attempts, **256 failed, 0 succeeded**, dominant error *"device disconnected or multiple access on port?"*.

## Bisect verdict (CIO-tasked)
- **Regression = US-441 (`ed5ec77`, 2026-07-03).** It widened `_ioLock` to guard `connect()`+`query()`+`disconnect()`, but `connect()` held it across the **entire** retry loop + backoff. A lifecycle wall-clock-timeout connect daemon is **left running on timeout**, so it monopolized `_ioLock` for minutes → `disconnect()` (the only path that closes the obd + releases the rfcomm bind) was starved → the failure path never closed the partial obd → the next `obd.OBD(portstr=/dev/rfcommN)` collided → 0 rows, permanent.
- **US-432 (`40809e7`) EXONERATED** — its RPM force latch is in `query()` (read path), which only runs after a successful connect; there were none.

## Fix — A+B (landed, unit-verified)
- **A:** `_ioLock` now acquired **per-attempt**, released across backoff (so `disconnect()`/`query()` can free the port); epoch fence re-checked each attempt → **A-17 serialization guarantee preserved**.
- **B:** partial obd closed on every failed attempt → no stale handle collides.
- **Evidence:** TDD RED→GREEN (`tests/pi/obdii/test_obd_connect_failure_cleanup.py`, DI, no hardware); full connect/thread-safety/reconnect/force/BT/capture/DTC suite green (~150 tests); ruff clean.
- **Commits on `dev`:** `78f6bc8` (fix + tests + finding), `332468b` (A2AL reply to Spool).
- **Lane note:** I implemented this directly under CIO direction (P0 incident, normally Ralph's lane), committed to `dev` out-of-sprint — same pattern as prior incident hotfixes. Flagging so you can reconcile versioning + the regression manifest.

## ⚠️ UNVALIDATED on hardware
Unit tests prove the lock lifecycle + cleanup logic; they cannot prove the real `obd.OBD()` handshake succeeds on the dongle. **One engine-on drive is THE gate** (rows in `realtime_data` + RPM + clean single-drive attribution). That same drive **also re-gates A-9, A-16 Bug-3, and BL-016** (fold in cold-boot-key-OFF → engine-on) — one drive closes four.

## Owed by you (PM levers)
1. **Deploy `78f6bc8` to the Pi** when appropriate. (Pi is back on-network after a `brcmfmac` host wifi-radio incident — resolved, network lane, unrelated to capture; the network-engineer filed you separate notes on the blackouts + a `packagekitd` OOM.)
2. **Versioning / backlog:** decide whether to wrap this as a story + bump the patch version for the manifest, or carry it as a tracked hotfix. Your call.
3. **Track the validation drive** as the A-17 gate; Spool has the confirm probe (`probe_obd_capabilities.sh`) ready and owns the data verification.

## Strategic follow-up (not this fix)
Option **C** = adopt Spool's known-working recipe (`obd.OBD(fast=False)` auto-detect, drop the forced `portstr` + self-managed rfcomm bind). Worth a spike to groom later; validate engine-on before committing.

— Atlas
