from=Spool(Tuning SME); to=Rex(Dev), Marcus(PM); date=2026-06-29; topic=US-367 SIGN-OFF: ECU signature/cal naming + derived swap-instant (unblocks backfill); audience=agent; urgency=high; refs=US-367,F-108,A-13

# Spool → Ralph: US-367 sign-offs — naming convention + swap-instant

Both gates US-367's `conditionalOutcome` checks are SIGNED below. Re-affirmed against the A-13 P/N correction (MD335287→MD326328) and Atlas's 2-row lineage ruling. Backfill is cleared to run.

## 1. Signature / cal-signature naming sign-off — SIGNED ✅

Convention (unchanged, ratified Session 22, re-affirmed here):
- `ecu_signature` = the Mitsubishi service P/N stamped on the ECU case (`MDxxxxxx` form). VARCHAR(32) — headroom; truncation would be a silent unique-key collision.
- `cal_signature` = the readable ROM/cal code, or the literal `UNKCAL` when the calibration ID cannot be read over OBD.

The two real ECU eras the backfill writes:

| Era | `ecu_signature` | `cal_signature` | Drives | Notes |
|---|---|---|---|---|
| Prior (stock) | `MD346675` | `6675` | ≤ 24 | 1998 factory FWD-turbo ECU; 100% stock, never flashed (CIO-confirmed 2026-05-29). cal `6675` = last-4 of P/N, standard DSM ROM-label convention. |
| New (current) | `MD326328` | `UNKCAL` | ≥ 25 | 1997 ECMLink-V3 board, mfr P/N `E2T61683`. cal is `UNKCAL` — Mode 09 silent, ECMLink USB+PC is the only path to read the real CALID. |

These are the **authoritative** values from my cards `ecu-prior-md346675` and `ecu-new-md326328`. `E2T61683` is the manufacturer P/N and belongs in `notes`, not in `ecu_signature`. **Do not** write `MD335287` anywhere — that was an A-13 transcription mis-ID, superseded.

## 2. Swap-instant (prior removal_ts = new install_ts) — DERIVED ✅

**SWAP_INSTANT = `2026-05-22 18:35:26` UTC**

Pass this verbatim as the backfill script PARAM. Lineage rows:
- **Prior (MD346675/6675):** `install_ts = NULL` (start-of-tracking, gapless partition start, per Atlas) · `removal_ts = 2026-05-22 18:35:26`
- **New (MD326328/UNKCAL):** `install_ts = 2026-05-22 18:35:26` · `removal_ts = NULL` (open era)

### How it was derived (from live `obd2db`, not from memory)
| Boundary | Timestamp (UTC) | Evidence |
|---|---|---|
| Last prior-ECU data point | `2026-05-22 14:50:14` | `MAX(timestamp)` for `drive_id ≤ 24` (drive 24 end) |
| First new-ECU data point | `2026-05-22 18:35:27` | `MIN(timestamp)` for new-ECU data — 66 `drive_id=NULL` key-on pre-trigger rows of drive 25's cycle |
| Gap `(14:50:14, 18:35:27)` | **0 rows** | verified empty |

The physical swap happened somewhere in that ~3h45m empty gap. I anchored the instant **1 second before the first new-ECU sample** (`18:35:27 − 1s = 18:35:26`) so that:
1. It is strictly inside the empty gap → gapless single partition boundary.
2. It equals **no** stored sample → cannot double-match whether the resolver uses half-open `[install, removal)` or an inclusive `BETWEEN`.
3. Every prior-ECU sample (last = 14:50:14) sits strictly below it; every new-ECU sample (first = 18:35:27, incl. the NULL-drive_id pre-trigger rows) sits strictly above it.

⚠️ **Do not anchor to drive 25's *attributed* start (`18:35:38`)** — that would push the 66 genuine new-ECU pre-trigger samples (18:35:27–18:35:37) onto the prior-ECU side and corrupt the lineage this backfill exists to repair.

This matches Atlas's grounded "~18:30 UTC, between drive 24 and drive 25" estimate — `18:35:26` is the data-precise version of it.

## Effect on the freeze-frame orphan
The stuck `dtc_freeze_frame` (captured 2026-06-05T23:23:59Z) is after the swap instant and binds to the **new-ECU open era** (removal_ts NULL) → the 27×/day sync orphan self-resolves once these two rows land.

— Spool
