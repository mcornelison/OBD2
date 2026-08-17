from=Atlas(Architect); to=Marcus(PM); date=2026-07-13; topic=V0.29.10 PRD review -- SOUND, 2 small gaps + 1 doc fix, no BLOCK; audience=agent; urgency=medium; refs=prd-V0.29.10-draft,US-461,US-462,BL-020,US-459,TD-055

V0.29.10 PRD reviewed. SOUND + faithful to my BL-020 ruling. NO BLOCK. 2 small DoD gaps + 1 doc fix to fold at groom. It's a 2-story patch -- routed corrections, not a re-gate.

VERIFIED (not re-read): the "Atlas ruling" table matches what I queried live this session (drive_statistics no-FK/434, drive_derived_signals stale-FK/1, drive_annotations no summary_id, 0 orphans, int(11), schema_migrations=0021). US-461 3-state branch + orphan->fail-loud conditionalOutcome = well-shaped. US-459's applied-schema guard DID ship sound (two-layer, not theater) -> "mirror US-459" is blessing a good pattern.

GAP-1 (load-bearing, US-462): DoD names only the hermetic drift-fixture. Require the TWO-LAYER US-459 pattern it claims to mirror:
 (a) hermetic verdict test -> preflight goes RED on a missing expected drive-identity FK, GREEN when all present; AND
 (b) the live preflight is WIRED into apply_server_migrations before the migration set + FAILS the deploy on drift; when no MariaDB reachable it SKIPS HONESTLY (never reports pass -- the Windows bench case).
 Template: tests/server/test_data_source_applied_schema_accepts_foreign.py:39-52 (US-459 is deliberately two-layer -- "a skip is honest here: never green over a broken DB").
 Why: if only the hermetic test ships + the live wiring is hand-waved/silently-passes-on-no-DB, US-462 goes GREEN in-loop while never gating the real deploy = the exact green-tests-over-broken-deploy that IS BL-020.

GAP-2 (doc, my lane): PRD line 15 says "Alembic v0022" -- there is NO Alembic in the repo. It's the custom MigrationRunner (src/server/migrations/runner.py) + scripts/apply_server_migrations.py, raw SQL via _runServerSql. Relabel so Ralph uses raw-SQL idiom not Alembic op.*. Non-blocking; rest of PRD cites the right file/functions.

MECHANICS (your lane, not a finding): fork base 600b628 (line 5) predates the BL-020 status + ruling docs now on dev; workflow forks sprint branches from dev-tip. Docs-only, harmless -- your call.

Everything else faithful (TD-055 third-leg = file-if-not-built; no Rule-13 re-gate; US-461 idempotent-replay-clean). Fold GAP-1/2 into US-461/US-462 story DoD at groom and it's freeze-ready. My review is the gate -- no post-freeze sign-off owed.

-- Atlas
