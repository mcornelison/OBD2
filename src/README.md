# src/ — OBD2v2 Source Tree

This tree is organized by deployment tier. See
`docs/superpowers/specs/2026-04-12-reorg-design.md` for the architectural
rationale.

## Top-level structure

- **`common/`** — Deployed to both tiers. Utilities, shared contracts, config schema, errors, logging.
- **`pi/`** — Deployed to Raspberry Pi only. Hardware, display, OBD data collection, orchestrator, simulator.
- **`server/`** — Deployed to Chi-Srv-01 only. FastAPI app, AI analysis, ingest, recommendation staging, MariaDB models.

## Deployment rule

The deploy script copies `src/common/ + src/<tier>/` to the appropriate host.
`src/pi/` never reaches the server. `src/server/` never reaches the Pi.

## Import rules

- Within a tier: use package-local relative imports (`from .X import Y`)
- Cross-package within a tier: use absolute imports (`from src.pi.obd.X import Y`)
- From tier to common: use absolute imports (`from src.common.config.validator import X`)
- **Tier-to-tier imports are FORBIDDEN.** `src/pi/` cannot import from `src/server/` and vice versa.

## Finding things

- Shared types (DriveLog, Recommendation, etc.): `src/common/contracts/`
- Config validation: `src/common/config/`
- Pi entry point: `src/pi/main.py`
- Pi orchestrator: `src/pi/obd/orchestrator/` (post-sweep 5)
- Server entry point: `src/server/main.py`
- Server AI: `src/server/ai/`
