---
id: F-083
parent: E-002
status: pending
renamedFrom: B-083
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-083: Mahalanobis-distance + per-metric Z-score baseline scoring for Spool drive grading

| Field        | Value         |
|--------------|---------------|
| Priority     | High (P1 — Ralph recommendation: HIGH for V0.28.0)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | S-M        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Add rigorous quantitative grounding to Spool's drive-grading layer. Compute pre-mod baseline mean + covariance once from the 4 pre-mod-shelf captures (drives 6/7/8/11 in `offices/tuner/knowledge.md`), then per drive emit (a) per-metric Z-scores and (b) overall multivariate Mahalanobis distance with confidence interval. Drops directly into Spool's existing Ollama prompt pipeline as numeric prefix.

**Why this technique fits our data:** zero ML training (just `numpy.cov()` + closed-form distance), captures multivariate structure ("this AFR is fine in isolation but anomalous *given* this RPM + load"), microsecond compute cost, interpretable Z-scores, drops into existing prompt pipeline.

**Source:** Ralph (Rex) PM note 2026-05-14 — research dive into `Bipra09/Anomaly-Detection-in-smart-cities` repo. Approved by CIO for backlog entry.

**Dependencies:** numpy (already a dep). No new packages.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
