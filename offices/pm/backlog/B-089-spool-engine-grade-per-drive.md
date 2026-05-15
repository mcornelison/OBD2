# B-089: GEM-4 — Spool engine grade per drive (A/B/C/D + 1-line reason)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (Spool Phase-3 V0.30; gated on B-083 Mahalanobis + B-093 baseline-relative anomaly)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | M        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Letter grade A/B/C/D + 1-line reason; surfaces post-drive as drive_summary footer.

**Inputs:** cumulative anomaly count + severity + thermal envelope + fueling stability + knock-retard events. Builds on B-083 Mahalanobis scoring + B-093 baseline-relative anomaly detection.

**Visibility:** POST-DRIVE ONLY per CIO A8 — real-time grade rejected (would turn driving into a game; safety-first conflict). Shown at next key-on as "Last Drive: B+, 1 minor coolant slope anomaly" footer in drive_summary view.

**Prior precedent:** Spool already grades drives in PM notes (drive 11 = "grade-A healthy"); productize the manual practice. Low complexity; high engagement.

**Source:** Spool gem-filter PM note (GEM-4 + CIO A8).


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
