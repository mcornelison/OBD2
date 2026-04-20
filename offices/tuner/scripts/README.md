# Spool — Review Scripts

Reusable, parameterized tooling for Spool's data-review rituals. Not production code. Not Ralph's lane.

## Purpose

When the CIO says "review the latest data and tell me if the engine is healthy," this tooling produces the same analysis shape every time — same queries, same grading structure, same output — so Spool's review is repeatable and auditable across sessions.

## Scripts

### `review_run.sh`

Pulls a time-sliced OBD dataset from both Pi SQLite and server MariaDB, reports PID coverage + value ranges + connection log + sync state. Output is then graded by Spool against Phase 1 thresholds (`offices/tuner/knowledge.md`).

**Usage**:
```bash
# The Session 23 first-real-data review (23-second idle capture):
./review_run.sh --since "2026-04-19 07:18:00"

# A bounded slice:
./review_run.sh --since "2026-04-19 07:18:00" --until "2026-04-19 07:21:00"

# Pi-only (server down or skip):
./review_run.sh --since "2026-04-19 07:18:00" --skip-server
```

Run `./review_run.sh --help` for all options.

**Prerequisites**:
- Passwordless SSH to `chi-eclipse-01` and `chi-srv-01` (see `reference_ssh_access.md` in auto memory)
- `sqlite3` on Pi (preinstalled)
- `mysql` client + readable `/mnt/projects/O/OBD2v2/.env` with `DATABASE_URL` on server

## Review Procedure (what Spool does with the output)

1. **End-to-end integrity**: Pi row counts, ranges, and averages must match server byte-for-byte. Any drift is a sync-layer bug (flag Ralph).
2. **PID coverage vs. Phase 1 spec**: Primary display expects RPM, Coolant, Boost, AFR, Speed, Battery Voltage. Absence of Boost (MAP 0x0B) and Battery (0x42) is expected on 2G ECU — see CR #1 (adapter ELM_VOLTAGE) in `2026-04-19-from-spool-real-data-review.md`.
3. **Threshold check**: Grade each PID's range against tiered thresholds in `offices/tuner/knowledge.md`. Flag anything hitting Caution or Danger.
4. **Health signals**: LTFT, STFT, O2 switching, MAF stability, RPM variation, engine load consistency. These are the heartbeat indicators.
5. **Connection log**: Look for mid-capture disconnects, retry storms, TD-023 MAC-as-path symptoms. Distinguishes "pipeline health" from "engine health."
6. **Capture window length**: Divide rows by distinct timestamps and number of PIDs to compute effective sample rate. Short windows limit diagnostic reach.

## Adding New Reviews

When Sprint 14's post-TD-023 drill lands (longer warmup + idle + shutdown), the same script runs with a wider `--since/--until` window. No code changes needed.

When CR #4 (data_source column) lands, add a `--source real` filter. The script already has an anchor comment where it'll plug in.

## History

- **2026-04-19** — Created during Session 23 closeout review. First use: Session 23 first-light real-data grading.
