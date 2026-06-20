# TD-049: Real-time telemetry monitor (research-only; deferred)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Research-only (deferred) |
| Status       | Deferred (revisit post-ECMLink V3) |
| Category     | tuner / observability  |
| Created      | 2026-05-10             |
| Filed By     | Spool 2026-05-10       |

## Description

Currently Spool only sees data POST-drive (after sync completes). A live "Spool watching the drive" mode would let Spool catch knock-pull events, thermal runaway, or unusual fueling in the moment instead of post-hoc.

## Why deferred

- We're K-line constrained at ~5 PIDs/sec; real-time monitoring is feasible but limited
- Requires server-side streaming (Pi -> server push every N rows, not just at sync)
- Requires alert mechanism (Spool can't watch dashboards 24/7)
- Marginal value vs post-drive analysis until drives become more frequent / risk increases (e.g., post-ECMLink, real WOT pulls)
- **Probably wasteful pre-ECMLink** -- knock pulls aren't directly observable on stock OBD-II anyway

## Trigger to revisit

When ECMLink V3 lands + actual knock data is available + drive frequency increases. Not a pre-mod priority.

## Notes

Filed as TD (research-only) rather than backlog because the value proposition depends on hardware that doesn't exist yet (ECMLink V3 install). Premature to spec.

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-new-tuning-research-and-feature-candidates.md` Item C
