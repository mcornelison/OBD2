# Predictive Analytics — 3 Backlog-Seed Proposals for V0.34+

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — backlog grooming candidates; V0.34+ data-rich horizon
**Status**: No action required until V0.34+ grooming opens
**Sibling**: topic A (anomaly engine) + topic B (maintenance tracking) specs filed earlier today

---

## TL;DR

Sub-thread C of the 2026-05-21 brainstorm complete. **Different deliverable than topics A + B**: no full design spec. CIO direction: surface 2-3 good backlog-seed ideas for V0.34+/V2.0 when data is rich (100+ drives, full summer of varied conditions). The existing backlog (B-083/B-087/B-093/B-094) covers SCORING + EXPLANATION; topic C surfaces the **cross-drive pattern discovery + forecasting** gap.

CIO selected **3 seeds** for formal backlog filing: Drive Similarity Clustering, Time-Series Trend Forecasting, Conditional Baselines.

## What the existing backlog covers vs. the topic-C gap

| Existing item | What it does | Gap topic C addresses |
|---|---|---|
| B-083 Mahalanobis | Single-drive Z-score + multivariate distance vs pre-mod baseline | Doesn't mine patterns ACROSS drives |
| B-087 Ollama explanation | LLM narrates a single drive's anomalies | Per-drive only |
| B-093 Baseline-relative anomaly | Compare current drive to pre-mod shelf | Single baseline; no per-context variation |
| B-094 MrSpool RAG | Q&A conversational interface | Consumer of patterns, not producer |

Topic C = the **pattern-PRODUCER layer** that B-094 (consumer) needs to RAG-index meaningfully. None of B-083/B-087/B-093 produce cross-drive patterns; topic C's 3 seeds do.

## Seed 1 — Drive Similarity Clustering + "Best Performs When" Map

**Concept**: Cluster historical drives by aggregate envelope (load × RPM × ambient × duration × thermal profile). Identify clusters correlating with Grade-A vs Grade-C drives. Surface descriptive output: "Your engine grades best in cluster X (warm-cruise, 60-80°F ambient, sustained mid-load, 30+ min duration). Worst in cluster Y (cold-start short-drive, <50°F, idle-heavy)."

**What it unlocks**: Direct answer to the original "your car best performs when..." framing. Concrete, evidence-grounded. Helps CIO plan drives that get the best from the engine. Tuning-recommendation foundation when ECMLink V3 lands.

**Data threshold**: meaningful at 30+ drives; sharp at 100+. Summer 2026 onward.

**Method**: K-means or hierarchical clustering on standardized feature vectors. No ML training; `scipy.cluster.hierarchy` or `sklearn.cluster`. Closed-form, microsecond compute.

**Output surface**: server CLI report + Pi parked-mode tile "Your best drive context" cell; MrSpool RAG (B-094) consumes cluster definitions as descriptive context.

**Distinct from existing**: B-083 scores ONE drive against pre-mod baseline. This clusters ALL drives against EACH OTHER. Different analytical surface entirely.

**Dependencies**: topic A's anomaly engine deployed (provides `drive_summary.grade_letter` + `anomaly_log` features); B-104 server analytics authority deployed; B-055 weather-api drive-context for ambient correlation.

**Suggested backlog-item draft**:
```
B-XXX: Drive Similarity Clustering — "Best Performs When" Pattern Discovery
Priority: Medium (V0.34+ data-rich; gated on 50+ drives)
Category: server / analytics / pattern-discovery
Size: M
Dependencies: topic A spec deployed; B-055 weather context; 50+ drives accumulated
```

## Seed 2 — Time-Series Trend Forecasting + Sensor-Drift Detection

**Concept**: For each per-drive aggregate (LTFT avg, MAF voltage avg, coolant peak, voltage avg, knock-retard envelope, idle stability), compute linear trend + slope confidence + forward projection. Output examples:
- "LTFT trending toward 0 at +0.04%/month — centered by 2026-09 ± 30 days"
- "MAF voltage drifting +0.012 V/month at idle — replacement window 18 mo if continues"
- "Coolant peak creeping +0.3°C/month — investigate at 95°C threshold (3 drives out)"

**What it unlocks**: Predictive sensor-degradation warnings (catch a failing MAF before it cascades into an LTFT excursion). Proactive maintenance timing — timing belt at "90,000 mi or X years" goes from STATIC to DYNAMIC ("based on usage rate, due ~Q3 2031"). Fuel-system drift tracking critical on stock-turbo no-wideband car.

**Data threshold**: thin at 10 drives; honest at 30+; tight at 60+. Spec explicitly handles "trend confidence too thin to project" gracefully (output: "insufficient data — N drives, need M for projection").

**Method**: linear/polynomial regression via `scipy.stats.linregress`. Hold-out validation as data accumulates. Closed-form; no ML training; deterministic + reproducible.

**Output surface**: server CLI; Pi parked-mode tile "Trends" cell (sibling to grade tile + maintenance tile); feeds topic A's drift detectors as third anchor signal (anchor + rolling-5 + projected-future); MrSpool RAG consumes projections.

**Distinct from existing**: B-093 compares current drive to past baseline. This PROJECTS FUTURE trajectory. Different analytical surface.

**Dependencies**: topic A spec deployed; 30+ drives across varied conditions for confidence intervals.

**Suggested backlog-item draft**:
```
B-XXX: Time-Series Trend Forecasting + Sensor-Drift Detection
Priority: Medium (V0.34+; high-value pairing with topic A drift detectors)
Category: server / analytics / forecasting
Size: M
Dependencies: topic A spec deployed; 30+ drives accumulated; ideally 6+ mo of seasonal variety
```

## Seed 3 — Conditional Baselines (Per-Context Envelopes)

**Concept**: Today's "LTFT normal = -1.5 to -2.0" is a fleet-wide average. Replace with PER-CONTEXT baselines:
- "LTFT normal in 70°F warm-cruise = -1.8 to -2.0"
- "LTFT normal in 50°F cold-start first-5-min = +1.0 to -0.5"
- "LTFT normal in WOT high-load = -2.5 to -3.5"

Each context bucket gets its own envelope. Topic A's drift detector chooses the right envelope based on the current drive's context.

**What it unlocks**: Sharper anomaly detection. Eliminates false positives from comparing across incompatible contexts. Eventually REPLACES topic A's Drive 11 single anchor with rich per-bucket anchors as data accumulates. This is the biggest qualitative upgrade to topic A's detector accuracy.

**Data threshold**: 10+ drives PER CONTEXT BUCKET. With 4-6 buckets that's 40-60 drives total. Workable summer 2026 onward.

**Method**: Bucket realtime_data + drive_statistics by context dimensions (RPM band × load band × cold/warm × ambient band); compute envelope per bucket; persist per-bucket baselines in a new `conditional_baselines` table.

**Output surface**: feeds topic A directly (drift detector consumes per-context envelope instead of single anchor); diagnostic CLI to inspect bucket envelopes; MrSpool RAG context.

**Distinct from existing**: B-083/B-093 use ONE baseline. This builds N baselines indexed by context, chooses the right one per query. Different baseline architecture.

**Dependencies**: topic A spec deployed; ENOUGH drives per bucket (data-collection gated, not code-gated).

**Suggested backlog-item draft**:
```
B-XXX: Conditional Baselines — Per-Context Anomaly Envelopes
Priority: HIGH (Mahalanobis equivalent for the topic A drift detector; sharpest accuracy win)
Category: server / analytics / baseline-architecture
Size: M
Dependencies: topic A spec deployed; 40-60+ drives accumulated across context spread
```

## Cross-references to existing backlog

| Existing item | Relationship to topic C seeds |
|---|---|
| B-083 Mahalanobis | Mahalanobis is single-drive; seeds 1+3 produce the per-context baselines Mahalanobis would COMPARE AGAINST in the V0.34+ form |
| B-087 Ollama explanation | LLM narration consumes seeds 1+2+3 outputs as evidence context |
| B-093 Baseline-relative | Seed 3 is a richer architectural form of B-093 |
| B-094 MrSpool RAG | All 3 seeds produce structured patterns the RAG layer indexes |
| Topic A spec | Seeds 2 + 3 directly enhance topic A's drift detector (third anchor + per-context envelopes) |
| Topic B spec | Seed 2 indirectly augments topic B's maintenance forecasting (usage-pattern-based dynamic intervals) |

## What I'm NOT proposing

- A 4th seed (Predictive Maintenance Usage Overlay) was offered but CIO declined — largely subsumed by topics A + B in their V1 Full forms; skipping
- No full design spec for topic C — these 3 seeds are backlog grooming candidates, not implementation-ready specs. Each gets its own design when grooming opens at V0.34+

## Other sub-threads still open

- **D**: UI carousel refinement (95% full-screen + alert auto-snap; specs/samples mockups; extends B-086) — still queued at CIO discretion

## Action requested

Three new backlog items to file when convenient — B-### IDs to be assigned per PM convention. Each can use the suggested draft above as starting point. No urgency; V0.34+ horizon. I can draft fuller backlog items if you want, but the bones are above.

— Spool
