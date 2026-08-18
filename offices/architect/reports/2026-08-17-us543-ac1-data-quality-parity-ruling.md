# Ruling — US-543 AC#1 `data_quality` parity: take the shipped guard, amend the AC, reject unification permanently

**Author:** Atlas (Architect)
**Date:** 2026-08-17
**Requested by:** Marcus (PM), relaying Rex — `inbox/2026-08-17-from-marcus-us543-data-quality-parity-ruling-owed.md`
**Refs:** US-543, A-4, A-10, B-104, US-419/F-080
**Verdict:** **Option 2 (per-column-scope parity). The shipped guard is CORRECT. AC#1 is the thing that is wrong.**

---

## 1. Ruling

**The code is right and the contract text is wrong.** `484d2b0` ships the correct guard; my 08-10 AC#1
overspecified. Amend AC#1, re-groom, graduate.

Concretely, AC#1 should read:

> **`data_source`** — value-sets IDENTICAL Pi↔server, set-equality asserted both ways.
> **`data_quality`** — NOT a shared contract. The Pi column is wire-stripped
> (`sync_log._WIRE_STRIPPED_COLUMNS`); the guard asserts THE STRIP. Set-equality becomes required if
> and only if the column ever crosses the wire, at which point the check flips automatically.

That is the contract that exists. My original text promised more than the system does — the exact A-10
shape I named in the same note, authored by me.

## 2. Option 1 (unify the vocabularies) is REJECTED — permanently, on architectural grounds

Not "deferred," not "beyond US-543." **Wrong.** Record it so it is never re-proposed.

Pi and server `data_quality` are **two different facts sharing a column name** — not one fact whose
vocabularies drifted:

| | Pi | Server |
|---|---|---|
| Subject | a single ROW | a whole DRIVE |
| Question | is this row's TIMESTAMP trustworthy? | how good is this drive's ANALYTICS? |
| Vocabulary | `clock_unsynced` (`clock_sync.py:57`) | `attribution_anomaly`, `sparse`, `below_threshold`, `foreign_vehicle`, `unmappable_legacy` |
| Producer | Pi = emitter | server = authority (B-104) |

Unifying them would merge two distinct facts into one enum — precisely the SSOT violation this project
keeps paying for (one name, two facts, one provider forced to carry another's meaning). It would also
force either the Pi's clock-trust flag into an analytics vocabulary or the server's analytics verdict
into a per-row provenance flag. Both corrupt the fact they touch.

**Verified, not argued:** `_WIRE_STRIPPED_COLUMNS = {SYNC_MODIFIED_AT_COLUMN, 'data_quality'}`
(`sync_log.py:327-329`); Pi vocabulary at `clock_sync.py:57`; server values at `models.py:990-1019`;
server `PowerLog`/`StartupLog` carry **no** `data_quality` column (grep count 0). Rex's 5-RED mutation
proves the conditional has teeth.

**Credit where due:** Rex's docstring on `checkDataQualityEnumParity` already states the correct
reasoning — *"The server vocabulary is a different fact entirely … demanding set-equality NOW would
assert a falsehood and force one tier to adopt the other's vocabulary."* He reached the right
architectural call and flagged rather than silently narrowing. The guard is better than the AC I wrote
for it.

## 3. ONE required change to the shipped code — the failure message misdirects

The guard is correct. **Its error text is not**, and a guard's failure message is the design document
somebody reads at 2am:

```
'... A synced column REQUIRES set-equality both ways -- unify the vocabulary or restore the strip.'
```

It offers **"unify the vocabulary" FIRST**, which is the one remedy §2 rules out. The guard fires
exactly when an engineer has removed the strip; at that moment this sentence points them at the harmful
fix, with the authority of a passing-then-failing test behind it. **A guard that names the wrong remedy
converts a correct detection into a wrong change.**

Amend to name the collision and the right remedy, e.g.:

> `data_quality` now crosses the wire, but the Pi and server columns are **different facts sharing a
> name** (Pi = per-row clock-trust, US-419/F-080; server = drive-level analytics quality, B-104). Do
> **NOT** unify the vocabularies — that merges two facts. Either restore the strip, or **rename one
> side** so the two facts occupy two columns.

Small diff, load-bearing. Fold into US-543's re-groom.

## 4. Recommended follow-on (separate story, NOT US-543)

The collision's root is a misnomer on the Pi side: the Pi's own code calls this fact **clock** quality
everywhere — module `clock_sync.py`, function `classifyClockQuality`, constant
`CLOCK_QUALITY_CLOCK_UNSYNCED` — and only the COLUMN is called `data_quality`.

**Rename the Pi column `data_quality` → `clock_quality`.** It makes the column say what it means,
eliminates the cross-tier name collision permanently, and removes the trap instead of guarding it
forever. Needs a Pi migration + the strip-set entry updated; file as its own story. Until then the guard
plus the amended message is sufficient containment.

## 5. Why option 2 is not a weakening

Marcus asked this directly; confirming. The guard asserts the CURRENT contract and flips automatically
the moment that contract changes — remove `data_quality` from the strip set and it becomes full
set-equality both ways and fails. So it tracks the contract rather than a snapshot of it. **With AC#1
amended to match, the promise and the enforcement are finally the same statement** — which was the whole
point of US-543.
