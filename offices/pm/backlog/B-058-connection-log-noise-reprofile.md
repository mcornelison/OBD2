# B-058: connection_log noise re-profile (post-V0.27.2 quiet-day audit)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low                    |
| Status       | Pending                |
| Category     | observability          |
| Size         | S                      |
| Related PRD  | None                   |
| Dependencies | V0.27.2 deploy must complete first (so we re-profile against the post-V0.27.1-heartbeat code) |
| Created      | 2026-05-09             |

## Description

Spool 2026-05-09 housekeeping note Item 3 finding: pre-V0.27.1 connection_log was hammering at ~2,640 connect_attempt + 440 connect_failure rows per DAY during Apr 24-28 (5 consecutive bench-running days, no driving). That's a connect attempt every ~33 seconds, 24/7.

Sprint 27 V0.27.1 hotfix added a 10s heartbeat + 30s connect timeout. Post-deploy worst-case projects to ~2,400 connect_attempt + 3,600 heartbeat rows per quiet-day. Whether this is healthy reconnect telemetry or runaway log spam depends on whether the new code suppresses logs once disconnected for >N minutes -- a question we can't answer from the data alone.

## Acceptance Criteria

- [ ] After V0.27.2 deploys + Pi runs quietly on bench for 5 days, query daily growth rate of connection_log
- [ ] Document daily row count in a Spool/Marcus PM note
- [ ] If still ~3k+ rows/day on a quiet day, file follow-up backlog item for log suppression / event coalescing
- [ ] If <500 rows/day on quiet day, close as "no action needed; healthy"

## Validation Script Requirements

- **Input**: 5 consecutive quiet (engine-off) days post-V0.27.2 deploy
- **Expected Output**: SQL query against `connection_log` showing daily growth rate
- **Database State**: per-day GROUP BY DATE(timestamp) row counts
- **Test Program**: simple query script -- no production code change needed for the audit phase

## Notes

**Sprint 29+ candidate**, contingent on V0.27.2 completing + a 5-day bench-quiet window.

**Side observation worth keeping**: connection_log daily row count is a free signal for "is the Pi running on bench right now?" -- could be useful for future diagnostics or as a regression test.

**connection_log shouldn't outpace realtime_data by ~30:1** the way it currently does on bench-only days. That ratio inverts in driving days (realtime_data grows fast, connection_log mostly idle).

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-post-cleanup-housekeeping-findings.md` Item 3
