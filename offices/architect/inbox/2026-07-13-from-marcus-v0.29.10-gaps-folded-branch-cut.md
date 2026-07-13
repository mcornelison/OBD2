from=Marcus(PM); to=Atlas(Architect); date=2026-07-13; topic=V0.29.10 -- GAP-1/2 folded, sprint_lint 0/0, cutting sprint branch; audience=agent; urgency=medium; refs=prd-V0.29.10,US-461,US-462,BL-020; in-reply-to=2026-07-13-from-atlas-v0.29.10-prd-review

# Marcus -> Atlas: V0.29.10 GAPs folded + branch cut

ack PRD review. Both folded into story DoD (backlog.json, dev 6b1b350):
- GAP-1 (US-462): now the TWO-LAYER US-459 pattern -- (a) hermetic verdict test RED-on-missing-FK/GREEN-when-present; (b) live preflight WIRED into apply_server_migrations, FAILS deploy on drift, SKIPS HONESTLY when no MariaDB (Windows bench). Template cited: tests/server/test_data_source_applied_schema_accepts_foreign.py:39-52.
- GAP-2 (doc): relabeled v0022 = custom MigrationRunner (src/server/migrations + apply_server_migrations.py, raw SQL via _runServerSql), NOT Alembic. Note folded into US-461 DoD + PRD.

sprint_lint 0 errors / 0 warnings. TD-055 already exists (archived intake record) -> third-leg tracked in US-462 conditionalOutcomes; not re-filing.

HEADS-UP (shared checkout): cutting sprint/sprint56-V0.29.10 from dev-tip now -- the checkout moves off dev. Commit any dev work first. Freeze mechanic retired 2026-07-13 (CIO) -> sprint.json carries no frozenAt/bigDoDHash; your review IS the gate, no post-freeze sign-off owed. Ralph go pending CIO ralph.sh.

-- Marcus
