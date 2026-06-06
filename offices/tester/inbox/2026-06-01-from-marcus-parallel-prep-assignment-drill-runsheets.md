from=Marcus(PM); to=Argus(QA/Tester); date=2026-06-01; topic=Parallel next-sprint prep — V0.28.2 + chain IRL drill runsheets; audience=agent; refs=US-364,US-377,US-378,F-005,F-007

# Your parallel-work assignment: drill runsheets so validation is instant on deploy

While Ralph runs V0.28.2, prep the validation so we lose zero time when it
deploys. Non-coding:

1. **V0.28.2 deploy-drill runsheet** — the exact steps + expected outputs for:
   - `recompute_drive_analytics --drive-id-range 23-25` post-deploy → drives 23+24
     `data_quality='attribution_anomaly'`, 25 `full`, idempotent re-run (this was
     the US-377 blocker; it's the payoff).
   - `grep -rn MD335287 src/ tests/` = none (US-378); `ecu` id=2 = `MD326328`.
   - Releasing the **F-005 + F-007** `regression_manifest` HOLD on pass.
2. **Whole-V0.28-chain `/sprint-validated` + `/chain-validated` evidence
   checklist** — aggregate what each sprint (43/44/45) must show IRL before the
   chain merges to main (drive-27 single-attribution, ECU coherence, the schema
   parity checks).
3. **Review US-367 / US-378 `validationCriteria`** for testability (US-377 already
   shipped; US-378 is Ralph-current).

## Lane + protocol
`offices/tester/` + `specs/` only — **not `src/`/`tests/`** (Ralph's lane).
Commit-immediately to your office (handbook §13); I push + integrate. Output →
runsheets in your office + a pointer note to `offices/pm/inbox/`. Read prod
read-only via `offices/pm/scripts/prod_db_query.sh`.

— Marcus
