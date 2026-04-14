# src/common/ — Shared Tier

Deployed to BOTH Pi and server. Contains only tier-agnostic code and shared
contracts.

## Structure

- **`config/`** — Config validator, secrets loader, config schema types
  - `validator.py` — config.json schema validation and defaults
  - `secrets_loader.py` — resolves `${ENV_VAR}` placeholders at runtime
  - `schema.py` — `AppConfig` dataclasses (tier-aware shape per Sweep 4)
- **`errors/`** — Error classification and handlers
  - `handler.py` — 5-tier error handler (retryable, auth, config, data, system)
- **`logging/`** — Logging setup
  - `setup.py` — logger configuration helpers
- **`analysis/`** — Pure stateless math used by both tiers
  - `calculations.py` — mean, stddev, outlier bounds (no state, no tier-specific deps)
  - `exceptions.py` — analysis-specific exceptions (InsufficientDataError, etc.)
  - `types.py` — analysis-specific dataclasses (ParameterStatistics, etc.)
- **`contracts/`** — Shared wire contracts (Pi↔Server protocol types). **Skeleton** — populated post-reorg when real data flows.
  - `protocol.py`, `drive_log.py`, `vehicle.py`, `alerts.py`, `recommendations.py`, `backup.py`
- **`constants.py`** — Protocol and schema version constants. **Skeleton**.

## Dependencies

- May import stdlib and minimal third-party libraries (e.g., `pydantic`, `jsonschema`)
- **Cannot import from `src.pi.*` or `src.server.*`** (tier-agnostic by design)
- Both tiers import from here
