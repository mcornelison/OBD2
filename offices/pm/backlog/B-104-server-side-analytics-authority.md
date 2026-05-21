# B-104: Server-Side Analytics Authority -- Pi as Emitter, Server as Analyzer (Architecture Epic)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (Sprint 41 / V0.27.17 Step 1 IN PROGRESS -- pulled forward from V0.28+ per CIO 2026-05-21 ratification: B-104 Step 1 IS the architectural fix for the V0.27.7/V0.27.16 false-pass class US-326+US-328+US-348+US-349) |
| Status       | **In Progress** (Sprint 41 / V0.27.17 advances Step 1: US-350 drive_summary compute + US-351 drive_statistics compute + table retire + US-352 backfill drives 12-20) |
| Category     | architecture / analytics / pi / server |
| Size         | L -- epic; Step 1 spans 3 Sprint 41 stories; Step 2+ (GEM family, Mahalanobis) remains V0.28+ |
| Related PRD  | offices/ralph/sprint.json Sprint 41 (Step 1 stories US-350/US-351/US-352); follow-on PRD opens post-V0.27 chain merge for Step 2+ |
| Dependencies | None (advance ratified 2026-05-21 ahead of V0.27 chain merge because it IS the bug-class fix); runs in parallel with B-076 (server schema normalization) at Step 2+ |
| Filed By     | Marcus (PM) per CIO 2026-05-21 directive |
| Created      | 2026-05-21             |

## Architectural Principle

**Pi = telemetry emitter. Server = analytics authority.**

- Pi captures raw OBD events + system events and syncs them to the server. That is the canonical data.
- Pi *may* compute in-drive aggregates locally for its own use (HDMI dashboard, real-time alerts) -- engine running = AC power, so this compute costs no battery. **These in-drive aggregates are NOT transmitted.**
- Pi **does** transmit any derived state that is *irreproducible from the raw event stream* -- e.g., an alert that fired + was acknowledged, transient diagnostic state that wasn't captured in raw events, user interactions. Default = "if the server could redo it from raw data, don't transmit it."
- Server computes all persisted analytics (drive_summary, drive_statistics, future GEMs, Mahalanobis baselines, ...) **from the raw event stream only**. Server is the sole writer for derived/persisted analytics tables.
- Recompute trigger: **overnight batch** over drives missing/stale summaries + **on-demand** recompute (when CIO wants fresh analytics or when analytics logic changes -- e.g., a Spool tuning-spec update).
- Recompute is **idempotent**: same raw data + same logic = same result. Safe to re-run.

## Why

- Pi at home runs on UPS battery (key-off, engine-off). On-time is scarce. Burning Pi cycles on analytics the server can redo from canonical data is wasted battery.
- Server has unlimited power, more compute, more memory, and already holds the raw data.
- Eliminates an entire class of Pi-vs-server divergence bugs (today's drive_summary has had multiple sync/lookup issues -- US-326 NULL fields, US-348 server writer fix, B-100 empty shells, the various _ensureDriveSummary IntegrityError silent-rollback issues).
- Enables retroactive analytics: when Spool updates a tuning spec or threshold, server re-runs over historical data with new logic. No Pi-side data migration.
- Sets up the V0.28+ analytics expansion (GEM family B-086..B-094 from Spool's 2026-05-14 brainstorm; Mahalanobis B-083 from Ralph's V0.28 research; future tuning-aware analytics) to live server-side from day one rather than getting retrofitted later.

## Step 1 -- drive_summary Migration (concrete deliverable, this epic)

- Remove Pi-side drive_summary writer entirely; Pi no longer emits a drive_summary row.
- Server gains a `compute_drive_summary(drive_id)` path that reads raw events (drive_events, obd_events, etc.) + writes `drive_summary` rows.
- Overnight batch job iterates over drives missing or stale summaries.
- On-demand CLI / endpoint to recompute a single drive or a date range.
- B-100 (drive_summary writer broken / empty shells), US-326 (server analytics NULL fix), US-348 (server writer fires) all SUPERSEDED on close-out -- the writer rewrite is the resolution.

## Step 2+ (in scope for this epic, broken out at PRD time)

- **drive_statistics migration**: same pattern. US-349 (Pi-side drive_statistics writer, just shipped Sprint 40 / V0.27.16) SUPERSEDED -- Pi-side writer retired in favor of server-side compute.
- **GEM family** (B-086..B-094 Spool brainstorm): land each GEM as a server-side computer from the start.
- **B-083 Mahalanobis baseline scoring** (Ralph's V0.28+ recommendation): server-side from day one.
- **Per-tuning-spec recompute**: when Spool publishes an updated spec, run on-demand recompute over affected drives.

## Acceptance Criteria (epic-level; per-story criteria at PRD time)

- [ ] Pi-side drive_summary writer code path removed (no Pi commits to drive_summary table; no Pi -> server sync of derived analytics rows).
- [ ] Server has a `compute_drive_summary(drive_id)` path that produces a drive_summary row identical to today's contract (same column shape, same semantics) from raw event data only.
- [ ] Overnight batch job iterates over drives with missing or stale drive_summary rows + computes them. Job is idempotent (re-running over the same drives produces the same output).
- [ ] On-demand recompute path exists for single drive + date range (CLI or endpoint; design at PRD time).
- [ ] Historical drives (1-12 + any post-V0.27 drives) get backfilled drive_summary rows via the new server-side path. Verifies the new path produces same-or-better summaries than the existing rows.
- [ ] B-100, US-326, US-348 closed as SUPERSEDED with cross-link to this epic.
- [ ] Pi in-drive aggregates (for dashboard / alerts) remain functional -- regression-tested against current dashboard behavior.

## Design Decisions Encoded (CIO 2026-05-21)

| Decision | Choice | Rationale |
|---|---|---|
| Pi-side fate | Pi computes during drive (engine = AC, no cost) for local use; **does not transmit** derived data; server recomputes from raw as authority | No reconciliation logic; no Pi-server divergence class; server is single source of truth |
| Transmission rule | Pi transmits raw events + *irreproducible* derived state only | Anything server can redo from raw data stays local |
| Server trigger | Overnight batch + on-demand recompute | Lowest server load; idempotent; freshness via on-demand when CIO wants it |
| Authority | Server is sole writer of persisted analytics | Eliminates dual-writer race / divergence |

## Open Questions (PRD-grooming time)

1. **"Irreproducible derived state" definition**: what concretely qualifies? Examples: alert-fired-and-acknowledged events, user interactions, transient diagnostic state not in raw stream. Spool + Atlas to nail down the inclusion rule at PRD time.
2. **Overnight batch scheduling**: cron, systemd timer, or in-process scheduler inside `obd-server`? PM lean: systemd timer on chi-srv-01 (consistent with how Pi services are managed). Decide at PRD.
3. **On-demand API surface**: CLI tool (`python -m obd_server.recompute --drive 12`) vs. HTTP endpoint vs. both? Likely CLI first; endpoint if a future UI needs it.
4. **Historical backfill scope**: all drives 1-12 + every drive post-V0.27.7 (when current server-side path stabilized)? Or only re-do drives where existing summary is NULL / suspect? PM lean: backfill all, since the server compute is idempotent.
5. **Schema fit with B-076**: B-076 (server schema normalization) is V0.28's chosen theme. B-104 changes the writer; B-076 changes the schema shape. They should land in compatible sequence -- ideally B-076's schema-design phase consumes B-104's writer-design constraints. PM to coordinate at PRD time.
6. **In-drive aggregate audit**: which Pi-side in-drive computations are *consumed locally* (dashboard, alerts) vs. *transmitted today*? Audit before removing transmission paths. Engagement with Spool needed.

## Validation

- **Synthetic**: unit tests for `compute_drive_summary(drive_id)` against fixture raw event streams; idempotency test (run twice, identical output); recompute-over-stale test.
- **DB read-back**: drive_summary rows for drives 1-12 produced by server-side path match the columns + semantics of the existing rows (modulo any bugs the rewrite fixes).
- **IRL**: drive N (post-deploy) syncs raw to server; overnight batch produces drive_summary row; on-demand recompute reproduces same row.
- **Pi-side regression**: dashboard + alerts work same as today during a drive (in-drive aggregates still computed locally for these consumers).

## Notes

- This is the framing for the V0.28+ server analytics expansion. Drive_summary is the concrete Step 1; the architecture epic is what's actually being filed here.
- Sits alongside (not before / after) B-076 (server schema normalization). Both are V0.28+; they should share PRD-grooming time so they land compatible.
- Related: B-076 (schema normalization), B-083 (Mahalanobis), B-086..B-094 (Spool GEM family), B-100 / US-326 / US-348 / US-349 (current drive_summary + drive_statistics work, all candidates for SUPERSEDED close-out under this epic).
- The Pi power-on-time-at-home constraint that motivated this is also why B-043 (Pi auto-sync + conditional-shutdown) exists. B-104 reduces the Pi's at-home workload, which improves B-043's headroom (less compute = faster sync-then-sleep).
