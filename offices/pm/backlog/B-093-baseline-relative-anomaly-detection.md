# B-093: GEM-8 — Baseline-relative anomaly detection (vs pre-mod shelf, not generic thresholds)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (Spool Phase-4 V0.31-V0.33; gated by B-083 Mahalanobis)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | M-L        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Compare current drive to pre-mod baseline shelf (drives 6/7/8/11) — not against generic thresholds. Aligned with stock-turbo-no-wideband reality where generic thresholds don't fit our setup.

Our existing `drive_statistics` table already supports per-PID baselines; need feature-extraction layer on top. This is the platform that GEM-2 anomaly detection (B-087) runs on; companion to B-083 Mahalanobis.

**Source:** Spool gem-filter PM note (GEM-8).


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
