# Sprint 27 Candidates (queued for grooming after Sprint 26 close)

Aggregated list of pre-groomed stories ready for Sprint 27 contract. Pulled from Spool's 2026-05-08 P0 inbox note + carryforwards.

## P0 — Spool 2026-05-08 engine-on-test-blocked (BLOCKING DRIVE 6)

Engine-on test 2026-05-08 captured **0 realtime_data rows** despite ~15-min engine-on window. Two bugs sitting behind Sprint 25's `_initializeConnection` fix: silent reconnect daemon + `_handleConnectionRestored` doesn't restart data logger. Per Mike's 2026-05-08 standing direction "the OBD Bluetooth needs a 10-second heartbeat listening to see if alive."

| ID | Title | Size | P | Source |
|---|---|---|---|---|
| US-301 | obd-reconnect-heartbeat (10s cadence + boot canary + loud bails) | M | 0 | Spool 2026-05-08 Story A |
| US-302 | data-logger-restart-on-connection-restored (idempotent + health field) | S | 0 | Spool 2026-05-08 Story B |
| US-303 | engine-on bench harness (extends US-286; would have caught both bugs) | S | 0 | Spool 2026-05-08 Story C; deps US-301 + US-302 |

Total: **1M + 2S = 4 size-points**.

**Critical timing**: A+B+C MUST land before Pi-wiring activates car-coupled lifecycle. Mike's car-wiring schedule per Spool's note: weekend ~5/9. Each story has 10-sec heartbeat + boot canary discipline (V0.24.1 anti-pattern lesson applied).

## Carryforward from Sprint 25 (still pending)

- **Drive 6 = post-jump LTFT review ritual** — Spool inbox handoff (NOT a sprint story)
- **First street-driving capture** — CIO action + small documentation story optional
- **Pre-mod baseline shelf** — 3-5 drives May/June for tuning baseline (data-collection milestone, no sprint impact)

## Pattern observation from Rex (Sprint 26 progress.txt)

Rex flagged that **phantom-path drift hit 11 cases in Sprint 26 alone** (US-287/289/290/292/293/294/295/296/297/298/299). The most severe was US-300 (BL-010 — wrong table name, not just wrong file path). Rex recommends formalizing this as a standing scope-fence amendment. PM action item filed for after Sprint 26 close — extend US-274 lint or add a pre-grooming verification step.

## Sprint 27 size summary

| Bucket | Stories | Size points |
|---|---|---|
| Spool P0 (engine-on critical path) | 3 | 4 (1M + 2S) |
| **Total queued for Sprint 27** | **3** | **~4** |

Plus whatever Mike adds at grooming time (B-007 touch screen? B-035 Spool thresholds? B-041 Excel CLI? More Spool follow-ups?).

## Anti-blocker discipline at grooming time

- All UPDATE paths verified on disk via US-274 file-existence check
- US-282 commit-vs-claim verifier active for sprint close
- Architectural choices upfront per BL-009 lesson (US-301 cadence values, US-302 health-field shape mandated)
- Runtime-validation gate per `feedback_runtime_validation_required.md` (every fix story has synthetic test that FAILS pre-fix)
- **NEW** per BL-010 lesson + `feedback_pm_verify_table_names_against_code.md`: PM verifies all table/path/symbol names against source code BEFORE writing into contract

## Notes

- Sprint 27 RELEASE bump V0.26.0 → V0.27.0 (MINOR; new safety-critical instrumentation surface)
- Per `feedback_pm_semver_convention.md`: major=0 until V1.0.0 stable milestone
