# B-092: GEM-7 — System status tile (BT link, last sync, Pi power mode, ladder stage)

| Field        | Value         |
|--------------|---------------|
| Priority     | High (Spool Phase-1 V0.28-V0.29 priority order: now -- addresses BT-reconnect bug visibility; small UI work, high CIO value)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | S        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Shows BT link state + last sync + Pi power mode + ladder stage if applicable. **DIRECTLY addresses the 2026-05-13 BT-no-reconnect bug visibility gap (I-033)** — eliminates the "did it capture my drive" surprise.

**Spool's recommended immediate-grooming candidate** (top of priority order post-CIO Q1-Q8 answers). Small UI work; high CIO value; addressable now even before bigger UI investment.

**Source:** Spool gem-filter PM note (GEM-7). Spool offered to draft preliminary PRD on PM go-ahead.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
