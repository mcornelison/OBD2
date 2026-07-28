# A-17 / capture-dead-since-0703 — RCA bisect + A+B fix (US-441 connect-lock regression)

**Date:** 2026-07-28 (session opened 2026-07-27)
**Author:** Atlas (Architect)
**Severity:** HIGH — top project blocker; 24 days of zero engine data
**Refs:** Spool note `inbox/2026-07-27-from-spool-obd-bt-capture-dead-since-0703.md`;
US-441 (`ed5ec77`), US-432 (`40809e7`); A-17; F-117; BL-016;
network-engineer notes `inbox/2026-07-27-from-network-rca-*` (×3)
**Files:** `src/pi/obdii/obd_connection.py`; `tests/pi/obdii/test_obd_connect_failure_cleanup.py`

---

## 1. Verdict (bisect)

**Regression = US-441 (`ed5ec77`, 2026-07-03). US-432 (`40809e7`) is EXONERATED.**

- US-432 only added the RPM force-mandatory latch **inside `query()`** — the read
  path, which runs only *after* a successful connect. Spool's ground truth = **0
  successful connects** (256/259 failed), so US-432's code never executes. It is
  downstream of the failure. Ruled out.
- Two other early hypotheses were **refuted by reading the code** (verify-before-
  asserting): the supported-PID probe does NOT call the locked `query()` — it
  reads `obd.supported_commands` directly (`pid_probe.py:121`) → **no deadlock**;
  and the probe call was already in the connect-success path pre-07-03 (US-199,
  not new).

## 2. Mechanism (all verified in code)

US-441 renamed `_connectLock` → `_ioLock` and widened it to guard `connect()`,
`query()`, AND `disconnect()`. But `connect()` acquired `_ioLock` **once** and
held it across the **entire** `_performConnect` retry loop **including the backoff
sleeps** (up to ~3.5 min on a failing link: 6 × 30 s timeout + [1,2,4,8,16] s).

1. The lifecycle wraps connect in a 30 s wall-clock timeout daemon and **leaves it
   running on timeout** (`lifecycle.py:798`). A timed-out connect keeps **holding
   `_ioLock` for minutes.**
2. `disconnect()` — the only path that closes the obd and **releases the rfcomm
   bind** — also needs `_ioLock`, so while the orphaned connect holds it,
   **`/dev/rfcommN` is never cleanly released.**
3. The connect failure path never closed the partial `obd` before the next attempt
   (`_performConnect` `except` just logged + retried), and the one function that
   would (`disconnect`) is locked out. So a **stale half-open handle** on
   `/dev/rfcommN` survives, and the next `obdlib.OBD(portstr=/dev/rfcommN)`
   constructor collides → **"device reports readiness to read but returned no data
   (device disconnected or multiple access on port?)"** → 0 rows. **Permanent.**

**Why it worked through drive 34 (07-03) and never after:** pre-US-441,
`disconnect()` and the logger's reads held **no lock**, so the port could be
cleaned/cycled concurrently even while a connect ground through retries. US-441
serialized all three behind the long-held connect lock, **removing the recovery
path** — the fix meant to stop "multiple access on port" now *causes* it.

(The 07-17 `4a17bc1` fix patched the DTC-read bypass in `dtc_client.py` — a
different site — so it never touched this connect-path monopolization; capture
stayed dead. F-117 was "unvalidated on a drive"; Spool's data is that validation.)

## 3. Fix — A+B (shipped, TDD)

- **(A)** `_ioLock` is now acquired **per attempt** around only the discrete port
  work (resolve + `obd.OBD()` construction + probe) and **released across the
  backoff sleep**, so `disconnect()`/`query()` can interleave and free the port.
  The **US-441 epoch fence is re-checked at the top of each attempt** (under the
  lock) — because the lock is now free across backoff, a newer connection may have
  won meanwhile, and a superseded daemon must fence rather than re-open. This
  **preserves the A-17 guarantee** (never two threads on the port at once).
- **(B)** new `_closePartialConnection()` closes the partial `obd` on every failed
  attempt (and on final failure) before the next open — no stale half-open handle
  survives to collide.

**Tests (`test_obd_connect_failure_cleanup.py`, DI factory, no hardware):**
- RED confirmed on pre-fix code: `closed flags = [False, False, False]` (B);
  `disconnect() blocked >1s (1.01s)` across backoff (A).
- GREEN after fix; **full connect/thread/reconnect/force/BT suite stays green
  (101/101)** — A-17 serialization + epoch-fence guarantees intact. Ruff clean.

**Unvalidated on hardware.** Needs one engine-on drive: rows land in `obd.db`
`realtime_data`, RPM reads, clean single-drive attribution. That drive also
re-gates A-9, A-16 Bug-3, and BL-016 (cold-boot-key-OFF → engine-on).

## 4. Network cross-reference (CIO ask) — sync/BT are NOT the capture cause

From the three network-engineer notes + code:
- **Server-sync exonerated as a capture-interference vector.** The sync client
  gates on a **zero-packet UDP route probe** (`client.py:435-470`); drive-time (no
  route to `.120`) → it transmits nothing → no combo-radio contention with BT
  capture. Sync runs only on garage arrival, parked — temporally separated from
  capture.
- **BT/WiFi coexistence disproven** as the WiFi fault (BT moved 0 bytes during the
  WiFi blackouts). The blackouts are a **`brcmfmac` host driver/firmware fault** +
  a separate **WPA 4-way-handshake** drop — both host-side, network lane, **not
  the OBD app** (exonerated twice by controlled A/B).
- **Not the capture cause:** capture failure is date-correlated (07-03) and ~100%
  (256/259) — a code regression, not intermittent RF contention. But fix (B) also
  hardens the connect path against **genuine** transient rfcomm drops (clean up +
  retry rather than wedge), so it helps whatever residual in-car BT flakiness
  exists.

## 5. Strategic follow-ups (not this fix)

- **(C) — the known-working recipe.** Spool's `probe_obd_capabilities.sh` uses
  `obd.OBD(fast=False)` with **no `portstr`** (python-obd auto-detects) and reads
  live RPM, while the service forces `portstr=/dev/rfcommN` via its own rfcomm
  bind. Worth a spike to drop the self-managed bind and let python-obd auto-detect
  — sidesteps the rfcomm-lifecycle collision entirely. Larger change; validate
  engine-on before committing.
- **Sync-transport hardening (network-engineer's 3 architecture asks to Atlas):**
  idempotent/batched/store-and-forward pushes, don't sync on link-up (wait for a
  stability signal on garage arrival), design for 10–1000 ms RTT + multi-second
  stalls as normal. Separate design item; I owe them a reply. NOT a capture
  blocker.

A-17 stays **OPEN (HIGH)** until the live engine-on drive validates capture.
