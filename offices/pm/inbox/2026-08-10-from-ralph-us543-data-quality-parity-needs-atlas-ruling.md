# US-543 — the `data_quality` half of assertion A-4 #1 needs an Atlas ruling

**From:** Rex (Ralph / Dev)
**To:** Marcus (PM) → Atlas (Architect)
**Date:** 2026-08-10
**Re:** US-543 (F-119), acceptance criterion 1

## What the AC asked for

> 1. ENUM PARITY: `data_source` AND `data_quality` value-sets IDENTICAL
>    Pi↔server (set-equality both ways). Source of the A-10 saga (Pi got
>    'foreign', server didn't)

## What I built, and why it differs for `data_quality` only

`data_source` is implemented exactly as written: strict set-equality both ways,
both directions reported separately. That is the A-10 saga and it is now gated.

`data_quality` is **not a shared contract today**, so literal set-equality would
assert a falsehood:

| | Pi | Server |
|---|---|---|
| Vocabulary | `full`, `clock_unsynced` | `full`, `attribution_anomaly`, `foreign_vehicle`, `sparse`, `below_threshold`, `unmappable_legacy` |
| Meaning | US-419/F-080 post-reboot **clock-drift** flag | drive-level **analytics quality** |
| On the wire | **stripped** (`sync_log._WIRE_STRIPPED_COLUMNS`) | server computes its own at ingest |

The tiers deliberately disagree: B-104's "Pi = emitter, server = authority".
Server `power_log` / `startup_log` have **no** `data_quality` column at all.
Forcing set-equality now would require one tier to adopt the other's
vocabulary — a real architecture change, not a guard.

**So the guard asserts the contract that exists, and keeps the teeth:** while
`data_quality` is wire-stripped, parity is not required and the *strip* is what
is asserted. Remove it from the strip set and the check flips to full
set-equality both ways and fails until the vocabularies are unified.

Proven, not claimed — I mutated `_WIRE_STRIPPED_COLUMNS` to drop
`data_quality` and the gate went **5 RED**, headed by:

```
A1: data_quality now crosses the sync wire ... but the vocabularies differ:
    Pi-only=['clock_unsynced'],
    server-only=['attribution_anomaly','below_threshold','foreign_vehicle',
                 'sparse','unmappable_legacy']
A3 [power_log]:   the Pi puts 'data_quality' on the wire but the server has no such column
A3 [startup_log]: (same)
```

## The ask

Confirm the conditional reading, **or** tell me the AC meant something I have
not implemented. Two readings I can see if you disagree:

1. **Unify the vocabularies** (Pi adopts the server enum, or vice versa) so
   flat set-equality becomes true — a design change well beyond this story.
2. **Per-column-scope parity** — assert only over columns that actually cross
   the wire, which is what I built.

I am flagging rather than silently narrowing: an AC that says "IDENTICAL" and a
guard that says "identical *if synced*" are different promises, and PM/Atlas
own that call, not me.

## Grounding

- `src/pi/diagnostics/clock_sync.py` — `CLOCK_QUALITY_FULL` / `CLOCK_QUALITY_CLOCK_UNSYNCED`, and its own comment: "Pi-LOCAL honest-instrument flags — the server computes its own data_quality at ingest"
- `src/pi/data/sync_log.py::_WIRE_STRIPPED_COLUMNS` — the strip, with the same reasoning
- `src/server/db/models.py` — `DRIVES_/DRIVE_SUMMARY_/DRIVE_STATISTICS_DATA_QUALITY_VALUES`; `PowerLog` + `StartupLog` carry no `data_quality`
- Guard: `scripts/audit_sync_contract_parity.py::checkDataQualityEnumParity`
- Gate: `tests/lint/test_pi_server_contract_parity.py::TestA1EnumParity`
