from=Spool(Tuner SME); to=Marcus(PM); date=2026-06-28; topic=dtc_freeze_frame sync orphan — route to Ralph

# dtc_freeze_frame Sync Failing 27×/day — Orphaned Freeze-Frame, Broken Lineage Spine

**Date**: 2026-06-28
**From**: Spool (Tuning SME)
**To**: Marcus (PM) → for Ralph
**Priority**: Important (NOT safety-critical — engine data is unaffected; this is a sync-integrity + noise issue)

## Context

CIO did a drive today (2026-06-28). I verified it synced: drives 31 (2,743 rows, 16:17–16:25) and 32 (141 rows, 26s key-cycle tail) are on chi-srv-01, `realtime_data` syncs **completed, 0 errors**. Telemetry is fine.

**But** while checking, I found `dtc_freeze_frame` sync has been **failing every cycle** — 27 identical failures today alone, all citing the *same* record:

```
dtc_freeze_frame sync: no vehicle_info row for vin '4A3AK54F8WE122916'
active at 2026-06-05T23:23:59+00:00; cross-tier FK resolution failed (no silent re-resolve)
```

This isn't today's drive — it's ONE freeze-frame record from ~2026-06-05 stuck in the Pi's sync queue, retrying and failing on every sync since. `dtc_freeze_frame` on the server has **0 rows** — nothing has ever synced. CIO's directive: don't let errors like this linger.

## Root Cause (confirmed via DB inspection)

The resolver `_resolveVehicleInfoIdForCapture` (`src/server/api/sync.py:564`) binds a freeze-frame to a `vehicle_info` row purely by **VIN + ECU-lineage window** `[ecu_install_timestamp_utc, ecu_removal_timestamp_utc]`.

`vehicle_info` currently has **exactly one row**, and its window is degenerate:

| id | vin | ecu_id | ecu_signature | install_utc | removal_utc |
|----|-----|--------|---------------|-------------|-------------|
| 1 | 4A3AK54F8WE122916 | 3 | PRE_TRACKING_UNKNOWN | 2026-05-01 11:53:45 | **2026-05-01 11:53:45** |

Install == removal → a **zero-width, already-closed window**. There is **no open ECU era**. So *any* freeze-frame captured after 2026-05-01 11:53:45 fails to resolve — not just this one. The real ECU eras were never stamped into the lineage.

This is the **US-367 lineage-spine backfill** (already listed open in the project pointer). `stamp_ecu_swap.py` can't fix it — it requires a currently-active row to close, and there is none (it correctly refuses). Per that CLI's own docstring, ad-hoc SQL UPDATEs on `vehicle_info` are an anti-pattern that bypass the append-only invariant — so I did **not** hand-patch it. This is the ECU-identity SSOT and needs the sanctioned backfill path.

## Two distinct defects here

**1. DATA — broken lineage spine (the actual orphan cause). → US-367.**
The lineage was never properly bootstrapped. Land US-367 to write the real ECU eras (see ECU-identity truth below). Once the open `MD326328` era exists, the stuck June-5 freeze-frame resolves and syncs on the next cycle — self-healing.

**2. CODE HARDENING — infinite silent retry (the reason it lingered unseen). Separate story.**
A single unresolvable freeze-frame retries forever (27×/day for 3+ weeks) with no dead-letter / quarantine / alert. "Fail loudly, no silent re-resolve" is correct *per-attempt*, but at the queue level this is a silent infinite loop that would happily mask a *real* sync failure in the noise. Recommend: after N consecutive identical failures, quarantine the record (dead-letter table or `data_quality` flag) and surface it once, rather than re-failing every cycle. This is the discipline that keeps a benign orphan from hiding a malignant one later.

## ECU-identity truth for building the correct lineage (my lane — CIO-confirmed)

Ralph: the lineage spine should be (precise swap instant to be derived from drive data — last old-ECU drive end / first new-ECU drive start, ~2026-05-22 mid-afternoon):

- **ecu_id=1 — `MD346675` / cal `6675`** — 1998 factory flash, CIO-confirmed 100% stock. Drives ≤24. Era: start-of-tracking → 2026-05-22 swap instant (removal).
- **ecu_id=2 — `MD326328` / cal `UNKCAL`** — 1997 board + ECMLink V3, plug-installed 2026-05-22. Drives ≥25. Era: 2026-05-22 swap instant → **NULL (open)**.
- ecu_id=3 `PRE_TRACKING_UNKNOWN` is a placeholder; the spine backfill should supersede it.

The June-5 freeze-frame (captured 2026-06-05 23:23:59 UTC) is firmly in the **`MD326328`** era — it should bind to the ecu_id=2 row. Full ECU history is in `offices/tuner/knowledge.md` "ECU Identity" if Ralph needs the provenance.

## Acceptance criteria

1. `vehicle_info` has the correct append-only lineage: closed `MD346675` era + open `MD326328` era (single currently-active row; coherence check `vehicle_info_coherence.py` passes).
2. The stuck June-5 freeze-frame resolves and syncs → `SELECT COUNT(*) FROM dtc_freeze_frame` > 0, bound to the ecu_id=2 era.
3. `sync_history` shows no recurring `dtc_freeze_frame` failures after the fix.
4. (Hardening story) Repeated unresolvable cross-tier rows quarantine after N failures instead of retrying forever.

## Sources

- DB inspection: chi-srv-01 `obd2db`, 2026-06-28 (via `prod_db_query.sh`).
- Resolver: `src/server/api/sync.py:564` `_resolveVehicleInfoIdForCapture`.
- Sanctioned lineage writer + invariant: `src/server/cli/stamp_ecu_swap.py`.
- ECU identity: `offices/tuner/knowledge.md` "ECU Identity"; MEMORY.md ECU-identity entry.
