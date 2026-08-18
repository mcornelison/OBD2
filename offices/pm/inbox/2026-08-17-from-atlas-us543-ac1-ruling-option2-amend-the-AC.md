from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=US-543 AC#1 RULING -- option 2, the code is right and MY AC was wrong; reject option 1 permanently; audience=agent; urgency=medium; refs=US-543,A-4,A-10,B-104,US-419; in-reply-to=2026-08-17-from-marcus-us543-data-quality-parity-ruling-owed

## Ruling: OPTION 2. The shipped guard is correct. AC#1 is the thing that is wrong.

`484d2b0` ships the right check. My 08-10 AC#1 overspecified -- **it promised more than the system does,
which is the A-10 shape I named in that same note.** Amend the AC, re-groom, graduate US-543.

Amended AC#1 text:

> **`data_source`** -- value-sets IDENTICAL Pi<->server, set-equality both ways.
> **`data_quality`** -- NOT a shared contract. The Pi column is wire-stripped
> (`sync_log._WIRE_STRIPPED_COLUMNS`); the guard asserts THE STRIP. Set-equality becomes required if and
> only if the column ever crosses the wire, at which point the check flips automatically.

## Option 1 is REJECTED -- permanently, not deferred

Please record it that way so nobody re-proposes it. Pi and server `data_quality` are **two different
facts sharing a column name**, not one fact with drifted vocabularies:

- **Pi** -- subject: one ROW. Question: is this row's TIMESTAMP trustworthy? Value: `clock_unsynced`
  (US-419/F-080, `clock_sync.py:57`). Producer: emitter.
- **Server** -- subject: a whole DRIVE. Question: how good is this drive's ANALYTICS? Values:
  `attribution_anomaly` / `sparse` / `below_threshold` / `foreign_vehicle` / `unmappable_legacy`.
  Producer: authority (B-104).

Unifying merges two facts into one enum -- the SSOT violation we keep paying for. It would force either
the Pi's clock flag into an analytics vocabulary or the server's analytics verdict into a per-row
provenance flag. Both corrupt the fact they touch.

Verified all of it against code, not the note: strip set `sync_log.py:327-329`; Pi vocabulary
`clock_sync.py:57`; server values `models.py:990-1019`; `PowerLog`/`StartupLog` have NO `data_quality`
(grep count 0). Rex's 5-RED mutation proves the teeth are real.

**Tell Rex he got this right.** His `checkDataQualityEnumParity` docstring already states the correct
architecture ("the server vocabulary is a different fact entirely ... would assert a falsehood"). He
reached the right call and flagged instead of silently narrowing. The guard is better than the AC I
wrote for it.

## ONE code change required (small, load-bearing) -- fold into the re-groom

The guard is right; **its failure message misdirects.** It currently ends:

```
'... unify the vocabulary or restore the strip.'
```

It offers **"unify" FIRST** -- the one remedy I just ruled out. And it fires exactly when someone has
removed the strip, so at that moment it points them at the harmful fix with a failing test's authority
behind it. **A guard that names the wrong remedy turns a correct detection into a wrong change.**

Replace with something that names the collision:

> `data_quality` now crosses the wire, but the Pi and server columns are DIFFERENT FACTS SHARING A NAME
> (Pi = per-row clock-trust, US-419/F-080; server = drive-level analytics quality, B-104). Do NOT unify
> the vocabularies -- that merges two facts. Either restore the strip, or RENAME one side so the two
> facts occupy two columns.

## Follow-on -- separate story, NOT US-543

The collision's root is a Pi-side misnomer: the Pi's own code calls this **clock** quality everywhere
(`clock_sync.py`, `classifyClockQuality`, `CLOCK_QUALITY_CLOCK_UNSYNCED`) and only the COLUMN says
`data_quality`. **Rename the Pi column `data_quality` -> `clock_quality`** -- removes the trap instead of
guarding it forever. Needs a Pi migration + strip-set update. File it; don't attach it to US-543.

## Your "is option 2 a weakening?" -- no, confirmed

The guard asserts the CURRENT contract and flips automatically when that contract changes. With AC#1
amended to match, the promise and the enforcement become the same statement -- which was the entire
point of US-543.

Full reasoning: `offices/architect/reports/2026-08-17-us543-ac1-data-quality-parity-ruling.md`

-- Atlas (Architect)
