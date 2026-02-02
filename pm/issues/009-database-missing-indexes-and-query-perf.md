# I-009: Database Missing Indexes on connection_log and alert_log

| Field        | Value                          |
|--------------|--------------------------------|
| Severity     | Low (grows to Medium over time)|
| Status       | Open                           |
| Category     | database / performance         |
| Found In     | EXPLAIN QUERY PLAN analysis    |
| Found By     | Torque (Pi 5 Agent)            |
| Related      | I-006 (database readiness)     |
| Created      | 2026-02-01                     |

## Summary

During database deep inspection, EXPLAIN QUERY PLAN revealed that `connection_log` and `alert_log` have **no indexes**. Common queries on these tables perform full table scans. Currently low impact (13 and 0 rows respectively), but will degrade with months of driving data.

## Query Plan Analysis

| Query | Table | Plan | Impact |
|-------|-------|------|--------|
| `WHERE parameter_name = ? AND timestamp > ?` | realtime_data | SEARCH via `IX_realtime_data_param_timestamp` | GOOD |
| `WHERE profile_id = ? AND parameter_name = ?` | statistics | SEARCH via `IX_statistics_profile` | GOOD |
| `WHERE vin = ?` | vehicle_info | SEARCH via autoindex | GOOD |
| `WHERE event_type = ? ORDER BY timestamp DESC` | connection_log | **SCAN + TEMP B-TREE** | BAD |
| `WHERE profile_id = ? ORDER BY timestamp DESC` | alert_log | **SCAN + TEMP B-TREE** | BAD |

## Current Index Coverage

### Tables WITH indexes:
- `realtime_data`: 3 indexes (param_timestamp, profile, timestamp)
- `statistics`: 2 indexes (profile, analysis_date)
- `battery_log`: 2 indexes (timestamp, event_type)
- `power_log`: 2 indexes (timestamp, event_type)
- `ai_recommendations`: 1 index (duplicate)
- `vehicle_info`: 1 auto-index on VIN
- `profiles`: 1 auto-index on id

### Tables WITHOUT indexes:
- **`connection_log`**: 0 indexes — no coverage for event_type or timestamp queries
- **`alert_log`**: 0 indexes — no coverage for profile_id or timestamp queries

## Suggested Fix

```sql
-- connection_log: queries filter by event_type and sort by timestamp
CREATE INDEX IF NOT EXISTS IX_connection_log_event_type ON connection_log(event_type);
CREATE INDEX IF NOT EXISTS IX_connection_log_timestamp ON connection_log(timestamp);

-- alert_log: queries filter by profile_id and sort by timestamp
CREATE INDEX IF NOT EXISTS IX_alert_log_profile ON alert_log(profile_id);
CREATE INDEX IF NOT EXISTS IX_alert_log_timestamp ON alert_log(timestamp);
```

## FK Constraint Summary (for reference)

| Table | FK to profiles? | On Delete |
|-------|----------------|-----------|
| realtime_data | YES | SET NULL |
| statistics | YES | CASCADE |
| alert_log | YES | SET NULL |
| ai_recommendations | YES | SET NULL |
| connection_log | NO | — |
| battery_log | NO | — |
| power_log | NO | — |

Note: `connection_log`, `battery_log`, and `power_log` have no FK constraints. This may be intentional (hardware telemetry doesn't belong to a profile), but `connection_log` stores `mac_address` as 'profile:daily' which loosely references profiles.

## Current Table Sizes

| Table | Rows | Growth Rate |
|-------|------|-------------|
| realtime_data | 3,965 | ~500/simulate run (~13 params x 38 cycles) |
| statistics | 78 | 13/analysis run |
| connection_log | 13 | 2/drive (start + end) |
| alert_log | 0 | TBD (no thresholds exceeded yet) |
| vehicle_info | 1 | 1 per unique VIN |
| profiles | 2 | Stable |

## Impact

Low priority now. After weeks of real driving (multiple drives/day), connection_log and alert_log will grow. The full table scans will become noticeable when rendering drive history or alert dashboards.

## Recommendation

Add the 4 indexes to `ObdDatabase.initialize()` alongside the existing `CREATE INDEX IF NOT EXISTS` statements. Safe to run on existing databases (idempotent).
