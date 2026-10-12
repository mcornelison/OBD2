# US-808-a — preserved connection_log window (before 2026-06-01)

**Exported 2026-09-23. Nothing was deleted on either tier.** This export exists so that
the deletion story, if it is ever written, cannot destroy the evidence that explains
the 28,318-row difference US-808 was filed to investigate.

## Files

| file | rows | bytes | span |
|---|---|---|---|
| `pi_connection_log_before_2026-06-01.csv` | 44,704 | 3,908,664 | 2026-04-23 03:14:40 .. 2026-05-31 23:59:13 |
| `server_connection_log_before_2026-06-01.csv` | 16,386 | 2,503,278 | 2026-04-23 03:12:39 .. 2026-05-31 23:59:13 |

Both carry a header row and **every column of their source table**. Column sets differ
between tiers by design: the server adds the sync envelope (`source_id`, `source_device`,
`synced_at`, `sync_batch_id`).

**Total 6,411,942 bytes — under the 50 MB cap, so these are FULL exports, not samples.**

## Counts: reference vs live

The 2026-09-14 reference figures and the live figures at export time are both recorded in
`manifest.json`, deliberately, so a later reader can **see** drift instead of inferring it.

    44,704   Pi rows before 2026-06-01                    (reference 44,704 — no drift)
   -16,306   server rows, the three retry types           (reference 16,306 — no drift)
   -    80   explicit keeps (34 connect_success + 25 drive_start + 16 drive_end + 5 reconnect)
   -------
    28,318   exactly the gap US-808 was filed to investigate

Both tiers re-measured to the reference **exactly**. No stop-and-report condition was met.

## Per event type, same window

| event_type | Pi | server | difference |
|---|---:|---:|---:|
| connect_attempt | 33,566 | 11,675 | 21,891 |
| connect_failure | 8,236 | 4,598 | 3,638 |
| disconnect | 2,822 | 33 | 2,789 |
| connect_success | 34 | 34 | **0** |
| drive_start | 25 | 25 | **0** |
| drive_end | 16 | 16 | **0** |
| reconnect | 5 | 5 | **0** |

The four low-volume types match exactly; all of the difference is in the three retry types.
The analysis of what that means is US-808-b, not this file.

## One thing worth noticing before the analysis

⚠️ **The server's earliest row (03:12:39) is EARLIER than the Pi's (03:14:40).** The server
holds rows the Pi no longer has. Whatever explains the difference has to explain that too,
and it rules out any account in which the Pi is simply a superset of the server.

## Provenance

Read-only on both tiers. The Pi database was opened through a `mode=ro` URI and
`eclipse-obd` was never stopped; the server was read with a plain `SELECT`. Row counts,
header names and first/last timestamps were re-read from the written files and checked
against the source queries by `tools/export_connection_log_window.py` — an export that
cannot be re-read is a failed export.
