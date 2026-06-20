# TD-sweep4-legacy-validator-defaults: Legacy ConfigValidator DEFAULTS/REQUIRED paths unused by real code

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | cleanup                   |
| Affected     | `src/common/config/validator.py` (`DEFAULTS`, `REQUIRED_KEYS`) |
| Introduced   | 2026-01-21, project template |
| Surfaced     | 2026-04-13, Sweep 4 Task 8 (test fixtures) |
| Created      | 2026-04-13                |

## Description

The `ConfigValidator` module in `src/common/config/validator.py` carries forward a set of `DEFAULTS` and `REQUIRED_KEYS` entries inherited from the original Python template that the OBD2v2 codebase started from:

- `hardware.enabled`, `hardware.i2c.*`, `hardware.gpio.*`, `hardware.ups.*`, `hardware.display.*`, `hardware.telemetry.*`
- `backup.enabled`, `backup.provider`, `backup.folderPath`, `backup.scheduleTime`, `backup.maxBackups`, `backup.compressBackups`, `backup.catchupDays`
- `retry.*` (e.g. `retry.maxRetries`, `retry.retryDelayMs`)

None of these paths are read by any consumer in `src/pi/` or `src/server/`. The real OBD2v2 config shape uses `pi.powerMonitoring.*`, `pi.display.*`, `pi.alerts.*` etc. — all under tier-aware prefixes — and the hardware/backup sections are dead.

Sweep 4 Task 8 (test-fixture migration) deleted the two test classes that were exercising these legacy defaults — `TestHardwareConfigDefaults` and `TestBackupConfigDefaults` — because they were validating template-era behavior that no product code depends on. Roughly 31 tests were removed.

## Why It Was Accepted

Sweep 4 was scoped to test fixture migration only — no production code changes. Removing the legacy DEFAULTS/REQUIRED entries from the validator is a separate cleanup that wants its own small PR and a quick audit of `src/` to confirm nothing reads them.

## Risk If Not Addressed

- No functional risk — the entries are unused.
- Minor maintenance burden — new readers of `validator.py` see `hardware.*` and `backup.*` defaults and wonder where they are used.
- Mildly misleading — suggests the project has hardware/backup config that it does not.

## Remediation Plan

1. Grep `src/` for any reference to `hardware.`, `backup.`, or `retry.` in `config_validator` or direct config access — there should be none.
2. Delete those entries from `DEFAULTS` and `REQUIRED_KEYS` in `src/common/config/validator.py`.
3. Run full test suite. Fast suite should still pass at baseline count.
4. One small commit, bundled into a later "validator cleanup" sweep or folded into Sweep 6.

## Related

- Sweep 4 Task 8 (this session) — deleted the legacy test classes
- `docs/superpowers/plans/2026-04-12-reorg-sweep4-config.md`
