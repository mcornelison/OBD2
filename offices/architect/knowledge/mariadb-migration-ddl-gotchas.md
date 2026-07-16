# MariaDB migration-DDL gotchas (A-10 drift class — learned BL-020/021, 2026-07-13)

Reusable reference for ruling/reviewing server migrations against the live `obd2db`
(MariaDB 11.8.6 on chi-srv-01). The A-10 (ORM-vs-applied) drift class fired **4×**
in the V0.29 chain (BL-019 → BL-020 → US-459-trap → BL-021); these are the concrete
DDL facts that resolved them. Full narrative: `reports/2026-07-13-bl020-*` +
`reports/2026-07-13-bl021-*`.

## The root pattern (why this class exists)

Prod `obd2db` is built by **incremental ALTER migrations**; the migration *tests*
build the DB by **`Base.metadata.create_all`** (ORM) or SQLite. So a migration can be
**green on create_all/SQLite yet wrong on real MariaDB** — the ORM materializes
constraints the applied DB never got, and MariaDB-specific DDL semantics aren't
exercised. **Never rule/verify a migration from its tests or the ORM; query the
applied schema.** The durable guard is TD-055's real-MariaDB migration-chain test
(US-464 built; US-470 CI-gating pending Docker).

## Fact 1 — FK "missing on prod" (BL-020)

- `create_all` gives `drive_statistics.summary_id` an auto-named FK; the ALTER-built
  prod DB **never had it**. A migration that assumes an FK-to-drop fatals.
- **Fix shape:** probe `information_schema.KEY_COLUMN_USAGE` and branch **3-state** per
  table: FK→old = drop+re-point; FK→new = no-op; **NO FK = ADD-only** (skip the drop).
- **`ADD FOREIGN KEY` validates existing rows** → before ruling add-safe, verify
  **0 orphans** (`LEFT JOIN ... WHERE child NOT NULL AND parent IS NULL`) **and
  type-match** (both `int(11)`). Don't trust an "already aligned" code comment.

## Fact 2 — inline column CHECK is undroppable by DROP CONSTRAINT (BL-021)

A CHECK written **inline in a column definition** (`data_source VARCHAR(16) CHECK
(data_source IN (...))`) is named after the column and stored with it. Verified on
MariaDB 11.8.6 via a throwaway scratch table:

| DDL | Result |
|---|---|
| `ALTER TABLE t DROP CONSTRAINT data_source` | **ERROR 1091** — can't drop (name collides with the column) |
| `ALTER TABLE t DROP CHECK data_source` | **ERROR 1064 — invalid syntax.** `DROP CHECK` is **MySQL, not MariaDB** |
| `ALTER TABLE t MODIFY COLUMN data_source VARCHAR(16) …` | **OK** — inline CHECK stripped |

- **Fix = `MODIFY COLUMN`, definition-preserving.** A bare `MODIFY VARCHAR(16)`
  silently resets charset/collation → **introspect the real def and rebuild it**
  (the 5 obd2db tables: `VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  NOT NULL DEFAULT 'real'`).
- Branch **inline (name==column → MODIFY COLUMN) vs table-level (`ck_*` → DROP
  CONSTRAINT)** — table-level CHECKs drop fine by name; only inline ones need MODIFY.

## Technique — verify version-specific DDL on a throwaway scratch table

Do **not** rule a version-specific DDL fix from docs (the MariaDB doc pages did not
settle DROP CHECK; a web summary was actively wrong). Reproduce on the real server:
`CREATE TABLE _atlas_<slug>_probe (...reproduce the shape...)`, run each candidate
DDL, observe, then `DROP TABLE`. Non-destructive (scratch table, no real data),
uses `prod_db_query.sh` (app DB user, read+write), and gives a definitive answer.
This overturned the BL-021 `DROP CHECK` hypothesis **before** Ralph built it.

## Tooling

`bash offices/pm/scripts/prod_db_query.sh "<SQL>"` — runs against live obd2db via the
app's own async engine (password stays server-side). SELECT → tab rows; DDL → `OK`.
Prefer `information_schema` (`CHECK_CONSTRAINTS`, `KEY_COLUMN_USAGE`, `COLUMNS`,
`TABLE_CONSTRAINTS`) for applied-schema truth.
