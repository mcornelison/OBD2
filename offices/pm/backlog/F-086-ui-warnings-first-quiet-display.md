---
id: F-086
parent: E-001
status: pending
renamedFrom: B-086
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-086: GEM-1 — Warnings-first quiet UI on the 3.5" display

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (Spool Phase-2 V0.29-V0.30)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | L        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Screen idle by default; surfaces ONLY when something matters. Aligns with project safety-first principle and stock-turbo-no-wideband-no-knock-log conservative CIO context. Mockup B shows 6 big tiles INCLUDING a dedicated alert tile that lights up red on threshold.

**Spool-side thresholds ready:** coolant >104C (220F), voltage <12.0V steady, knock-retard >5 degree pull from drive-11 baseline under load, IAT delta-ambient >40C heat soak no recovery.

**CIO clarification 2026-05-14:** tiles are full-screen carousel-rotated (90-95% screen each, tap rotates), NOT all-visible dashboard. Warnings-first still applies as default view + auto-snap to alert tile on threshold trip.

**Source:** Spool gem-filter PM note `2026-05-14-from-spool-display-brainstorm-gems-filtered.md` (GEM-1). CIO Q1-Q8 answered inline (A2 confirmed).


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
