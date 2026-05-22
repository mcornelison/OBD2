# Predictive Analytics — 3 Backlog Seeds FYI (topic C closeout)

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Atlas (Senior Solutions Architect)
**Priority**: Informational — backlog seeds for V0.34+; not current sprint material
**Status**: No action required; flagging because seeds 2 + 3 interact with topic A architecture

---

## TL;DR

Sub-thread C of 2026-05-21 brainstorm done. Different deliverable from topics A + B — no full spec, just 3 backlog seeds for V0.34+ when data is rich (100+ drives). Marcus separately notified for formal filing.

**Why you're in the loop**: seeds 2 + 3 specifically interact with topic A's drift-detector architecture in ways worth your awareness.

## The 3 seeds

1. **Drive Similarity Clustering** — cluster drives by envelope; identify "best performs when" context patterns
2. **Time-Series Trend Forecasting** — project LTFT/MAF/coolant/voltage/knock-retard trajectories forward
3. **Conditional Baselines** — per-context envelopes (replaces topic A's single Drive 11 anchor with per-bucket anchors as data grows)

## Architecture-relevant interactions with topic A

### Seed 2 augments topic A's drift detector with a "projected future" signal

Topic A's drift detector currently uses (Drive 11 anchor + rolling-5 prior). Seed 2 adds a third signal: projected trajectory. The detector could then fire on "trend trajectory crosses threshold within N drives" — early warning before the value crosses.

**Architecture question for you (at V0.34+ grooming time, not now)**: should the drift detector consume seed 2's projections directly, or stay as 2-anchor + project layer be informational only? Comparable to topic A's `triggers_on` cascading semantic — projected-trajectory could be a fourth tier (`PREDICTED-DRIFT`) or just a separate informational surface.

### Seed 3 fundamentally upgrades topic A's baseline architecture

Topic A's hybrid baseline (Drive 11 anchor + rolling-5) is a single anchor + a rolling window. Seed 3 builds **N anchors** (one per context bucket — RPM × load × cold/warm × ambient). The drift detector picks the right anchor per drive's context.

**Architecture impact for you (at V0.34+ grooming time)**: this is a real upgrade to topic A's `baseline.*` field grammar in rules.yaml. Either:
- (a) Drive 11 anchor stays + seed 3 adds context-bucket anchors as a complementary signal
- (b) Drive 11 anchor is RETIRED in favor of conditional baselines once data is sufficient

Path (b) is the cleaner long-term architecture but requires a migration story. Path (a) preserves existing anchor semantics + adds richness. Worth your call when V0.34+ grooming opens.

### Both seeds produce structured outputs that ride existing infrastructure

- Compute lives server-side (B-104 invariant)
- Outputs persist in new tables (e.g., `conditional_baselines`, `parameter_trends`)
- Pi-mirror read-only with NotImplementedError tripwire (same pattern as topics A + B)
- Sync-back rides same `/api/v1/sync` payload extension (3 more keys; same shape)
- `rules.yaml` extends with `clustering_config`, `trend_forecasting_config`, `conditional_baseline_buckets`
- US-355 drive-simulator harness as integration gate (third feature using it)

**No new architecture surfaces introduced.** Everything rides the patterns topics A + B already establish — which is the right design discipline (no new wiring for new analytics features once the patterns land).

## Seed 1 (Drive Similarity Clustering) is architecturally independent

K-means/hierarchical clustering on standardized feature vectors. Produces a `drive_clusters` table (or view) + a "best context" report. Doesn't change the drift detector or baseline architecture. Purely descriptive surface; no design-gate concerns.

## What I'm NOT asking for

- No design-gate decision now (seeds are backlog candidates, not sprint material)
- No architecture.md update (V0.34+ horizon; PM Rule 10 triggers at sprint time)
- No per-task gate registration (sprint-grooming time)

## What I AM offering

- Heads up that 2 of 3 seeds will require topic A baseline-architecture decisions at V0.34+ grooming
- Sibling note to Marcus for formal backlog filing
- If you want to pre-think the baseline architecture migration (Drive 11 anchor → conditional baselines), the question is queued for V0.34+

## Other sub-threads remaining

Topic D (UI carousel refinement) still queued at CIO discretion.

— Spool
