# src/server/ — Companion Service Tier

Deployed to `chi-srv-01` only. Contains AI analysis and future FastAPI service.

## Structure

- **`main.py`** — Entry point (placeholder). Real implementation lands with B-022 US-CMP-001.
- **`ai/`** — AI analysis — **real code** migrated from `src/ai/` in sweep 3. Contains: analyzer, data_preparation, prompt_template, ranker, ollama, types, helpers, exceptions.
- **`api/`** — FastAPI app, routes, middleware. **Skeleton** — B-022 US-CMP-001, 002, 008.
- **`ingest/`** — Drive log ingestion, delta sync. **Skeleton** — B-022 US-CMP-004.
- **`analysis/`** — Post-drive deep analysis. **Skeleton** — B-031.
- **`recommendations/`** — Recommendation writer (writes to Pi inbox). **Skeleton** — B-031.
- **`db/`** — MariaDB schema and models. **Skeleton** — B-022 US-CMP-003.

## Dependencies

- Imports from `src.common.*` allowed
- Imports from `src.pi.*` **forbidden** (structurally enforced by deployment)
