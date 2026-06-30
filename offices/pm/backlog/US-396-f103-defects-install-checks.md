---
id: US-396
title: "F-103 defects + install-time checks (D-1/D-2/D-3 + V-1/V-2)"
type: normal
parent: F-103
epicId: E-001
size: S
status: sprint-ready
sourceRefs: [F-103, prd-V0.29.2, iris-f103-spec-v1.2, atlas-c5-2026-06-29]
created: 2026-06-29
---

# US-396 — F-103 defects + install-time checks (Iris US-D)

## Context

Closes the spec's known defects (D-1/D-2/D-3) and makes the install-time checks
(V-1/V-2) pass. May fold into US-393/US-394 at dev discretion with zero information
loss. Depends on US-395. BENCH-ONLY validation.

## Goal

As the F-103 surface, I want the spec's known defects closed + the install-time
checks passing.

## Definition of Done

- spec defects D-1/D-2/D-3 resolved
- V-1/V-2 install-time checks pass
- may fold into US-393/US-394 at dev discretion (zero information loss)

## Validation Criteria (bench)

- (re-run the D-1/D-2/D-3 repros) → (they no longer reproduce)
- (run V-1/V-2 install-time checks on a clean deploy) → (they pass)

## Conditional Outcomes

- may fold into US-393/US-394 at dev discretion (zero information loss)

## Notes

Build chain: US-393 → US-394 → US-395 → **US-396**.
