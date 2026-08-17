# Issue (unmasked by the chi-srv-01 IP fix) — `dtc_freeze_frame` sync returns HTTP 500

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Severity**: Med — non-blocking, non-corrupting, but `dtc_freeze_frame` never syncs to the server until fixed.

## Symptom
After the chi-srv-01 IP fix deployed to the Pi (sync now reaches `.120`), the Pi sync client
successfully pushes `realtime_data` and others (high-water advancing, `rowsPushed=500`/cycle),
but **`dtc_freeze_frame` fails all 4 retries with `HTTP 500 Internal Server Error`** from
`http://10.27.27.120:8000/api/v1/sync` (`failedTables=1` every interval).

Pi journal (2026-06-18 ~13:37):
```
sync push for dtc_freeze_frame -> http://10.27.27.120:8000/api/v1/sync attempt 1/4 failed: HTTP 500 Internal Server Error  (x4)
```

## Why it surfaced now (not caused by the IP fix)
Pre-fix, every table failed at the transport layer (`No route to host` to dead `.10`), so no
payload ever reached the server. Now that connectivity is restored, the server actually processes
each table's payload — and `dtc_freeze_frame` triggers a server-side 500. The bug is **latent and
server-side**; the IP fix merely unmasked it.

## Not corrupting / not blocking
- Failed pushes do **not** advance `sync_log.last_synced_id` (sync invariant), so rows re-queue;
  no data loss, no corruption.
- `realtime_data` (the critical telemetry) syncs cleanly. Only `dtc_freeze_frame` is stuck.

## Likely area (for whoever picks it up)
- `dtc_freeze_frame` is the Mode-02 freeze-frame table. Spool confirmed **Mode 02 is UNSUPPORTED**
  on the current ECU (MD326328), so the Pi-side table may hold edge/empty/legacy rows whose shape
  the server `/api/v1/sync` handler chokes on — or the server lacks a current `dtc_freeze_frame`
  ingest path / schema parity (smells like the A-4 Pi↔server schema-divergence family).
- Server-side stack trace from `obd-server.service` journal on chi-srv-01 will pinpoint it.

Recommend a small issue Story (server-side: handle/return-422 the `dtc_freeze_frame` payload, or
fix schema parity). Atlas can do the architectural diagnosis if useful; flagging now so it's tracked.

— Atlas
