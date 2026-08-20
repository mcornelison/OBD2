# Finding — `drive_summary.data_quality` DEFAULTS to `full`: "not assessed" is indistinguishable from "assessed and good"

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Found:** closing architectural review of the 2026-08-20 drive data.
**Severity:** Med-High (analytics trust); **contains an OPEN QUESTION — do not groom as settled.**

---

## 1. The schema defect (CONFIRMED)

Applied schema on prod (`information_schema`, verified live):

```
is_real        tinyint(1)    IS_NULLABLE=YES   COLUMN_DEFAULT=0
data_quality   varchar(20)   IS_NULLABLE=NO    COLUMN_DEFAULT='full'
```

**A quality VERDICT column whose default is the BEST verdict.** Any `drive_summary` row created without
an explicit computed value silently reads as `full` quality. **"Nobody assessed this drive" and "this
drive was assessed and is complete" are the same stored value.**

This is the week's recurring class, at the schema layer: `syncPending=0`, the IMU all-zero frames, the
latched magnetometer — and now a default verdict wearing the appearance of a measurement. Any consumer
filtering `data_quality='full'` cannot distinguish computed rows from untouched ones. No code review
catches this, because the code is innocent.

## 2. `is_real` anomaly (CONFIRMED, cause OPEN)

```
drive 38  data_quality=full  is_real=1
drive 39  data_quality=full  is_real=0     (parked idle session, SPEED 0 throughout)
drive 40  data_quality=full  is_real=0     REAL DRIVE, max SPEED 59
drive 41  data_quality=full  is_real=0     REAL DRIVE, max SPEED 56
```

`_deriveIsReal` (`src/server/analytics/drive_summary_compute.py:291-307`) can only return:

- `True` for `'real'`
- `False` for `'simulator'` — **not a valid `data_source` enum value**
  (`real`/`replay`/`physics_sim`/`fixture`/`foreign`)
- `None` for everything else

**So `is_real=0` is UNREACHABLE via this code path for any valid input.** The rows carry
`data_source='real'`, so the computed value should be `1` (or `NULL` if the event-log source were
absent). It is `0`.

The function's own docstring names this exact hazard:

> *"NULL preservation is load-bearing: silently coercing NULL to 0 (FALSE) is the failure mode that
> masked 'ungraded' drives as 'tested + not real' in earlier revisions."*

**The code preserves NULL correctly. Something downstream does not.**

## 3. OPEN QUESTION — not resolved before session end

**Leading hypothesis:** the analytics compute has NOT run for drives 39/40/41, and both values are
simply **schema defaults** (`'full'` and `0`) from row creation. That explains both observations at once
and requires no code defect beyond the schema.

**Could not confirm.** `drive_statistics` has 16–18 rows for `summary_id` 40–45, but `summary_id` is
`drive_summary.id` (a separate autoincrement PK), **not** `drive_id` — so those rows do not necessarily
correspond to drives 40/41. Resolving the mapping needs another query, and the Pi went off-network.

**To resolve (first thing next session):**

1. Map `drive_summary.id` → `drive_summary.drive_id` for drives 39/40/41.
2. Confirm whether the analytics batch (`server-analytics-batch.timer`) ran after 17:26Z 2026-08-20.
3. If it ran → `is_real=0` on `data_source='real'` rows is a genuine compute/persistence defect.
4. If it did not → the values are defaults, which makes §1 the whole finding, and a MORE important one.

**Either way §1 stands** and is worth fixing independently of the answer.

## 4. Fix shape (design owed to Atlas before grooming)

1. **`data_quality` must have NO default, or default to an explicit "not assessed" value.** A verdict
   column may not default to the best verdict. If NOT NULL is required, add an `unassessed` /
   `not_computed` enum member and default to THAT.
2. **`is_real` DEFAULT 0 should be DEFAULT NULL.** The column is already nullable and the code
   deliberately writes `None` for "ungraded"; a `0` default re-creates precisely the failure the
   docstring warns about.
3. **This is A-10 class** — ORM/code intent vs applied schema. The applied-schema guard
   (US-459 / US-462 pattern) should assert **DEFAULTS**, not only column presence and type. Today it
   would pass this cleanly.

## 5. Impact on today's conclusions

**None of my drive conclusions depended on these columns.** Row counts, timestamps, SPEED, drive
segmentation and the Pi↔server parity check were all read from `realtime_data` directly. **The A-9
result stands** (no overlap, clean back-to-back segmentation).

**But Spool must NOT filter his A-9 / US-526 analysis on `is_real=1`** — it would silently exclude both
real movement drives and produce the conclusion "there is no movement data." Warned separately.
