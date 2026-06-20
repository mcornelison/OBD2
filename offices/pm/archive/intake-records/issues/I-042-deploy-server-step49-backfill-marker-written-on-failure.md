# I-042: deploy-server.sh Step 4.9 writes idempotency marker on 0/10 backfill failure

| Field | Value |
|---|---|
| Filed | 2026-05-21 (Session 42, V0.27.17 deploy) |
| Filed By | Marcus (PM) |
| Severity | High (deploy-script semantics; idempotency marker means subsequent re-deploys silently skip the backfill even when prior attempt failed entirely) |
| Status | Open -- bundle into V0.27.18 hotfix alongside I-041 |
| Related | US-352 (Sprint 41), deploy-server.sh Step 4.9, I-041 (root cause of the 0/10 failure that exposed this) |

## Symptom

V0.27.17 server deploy Step 4.9 (drives 11-20 backfill) reported:

```
2026-05-21 21:45:32,132 INFO __main__ | recompute_drive_analytics |
done | success=0 | skipped=0 | failed=10
Backfill complete; marker written to
/mnt/projects/O/OBD2v2/.backfill-V0.27.17-drives-11-20-complete.
```

The marker file was written **despite** every drive failing. Idempotency logic (deploy-server.sh:~310 per the in-file comment) checks for marker presence on subsequent deploys; if the marker exists, Step 4.9 is skipped. This means once I-041 is fixed via v0009 migration and we redeploy, Step 4.9 will silently skip the now-fixable backfill until the marker is manually deleted.

## Root Cause

The marker-write logic treats Step 4.9 as "complete" based on **invocation success** (CLI exited 0), not on **outcome success** (success > 0). The recompute_drive_analytics CLI's best-effort design means it logs failures and exits 0 anyway -- so the deploy script sees "exit 0" and writes the marker.

This is the same class as the V0.27.7/V0.27.16 false-pass cluster (US-326/US-328/US-348/US-349): a wrapper observes "the thing ran" without observing "the thing actually did its job." Pattern Atlas labeled "trigger-seam observation without outcome verification."

## Fix Plan (V0.27.18 patch loop -- bundle with I-041)

1. **deploy-server.sh Step 4.9** must parse the CLI's `success=N | skipped=N | failed=N` output line and only write the marker when `failed == 0` (or `success >= drives_attempted`). On partial/full failure, WARN + leave marker absent so next deploy retries.
2. **Bonus**: pre-check for marker presence + log it explicitly so the operator sees "marker present → skipping backfill" vs "marker absent → attempting backfill".

## Workaround for V0.27.18 deploy

Before re-running Phase 6b for V0.27.18, manually delete the stale marker:

```bash
ssh chi-srv-01 'rm -f /mnt/projects/O/OBD2v2/.backfill-V0.27.17-drives-11-20-complete'
```

(The V0.27.18 deploy will look for a V0.27.18-named marker; the V0.27.17 marker name is now misleading anyway. Cleanup recommended.)

## Cross-links

- I-041 (the root cause that exposed I-042)
- US-352 (the backfill story whose deploy step is broken)
- Pattern: same "outcome-not-observed wrapper" class as the V0.27.7/V0.27.16 false-pass cluster
