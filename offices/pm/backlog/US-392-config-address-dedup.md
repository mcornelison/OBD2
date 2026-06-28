---
id: US-392
title: "De-dup the server address inside config.json (derive base URLs from serverHost:serverPort)"
type: tech-debt
parent: F-044
epicId: E-004
size: S
status: sprint-ready
sourceRefs: [A-15, F-044, atlas-a15-mirror-lint-2026-06-18, config-json-server-address-dedup-gap]
created: 2026-06-28
---

# US-392 — De-dup the server address inside config.json

## Context

A-15: the `.10`→`.120` server move broke sync because `config.json` holds the
server address in multiple literals (`serverBaseUrl` / `companionService.baseUrl`)
that nothing forces to agree. Atlas built a mirror-consistency lint
(`scripts/audit_address_mirrors.py` + `tests/lint/test_address_mirror_consistency.py`)
as a guard against divergence; this Story removes the duplication that lint guards
by deriving the base URLs from `serverHost:serverPort` so the literal lives in ONE
key — a box move becomes one edit.

## Goal

As the infrastructure config, I want the A-15 structural gap behind the .10->.120
breakage closed: config.json holds the server address in multiple literals
(serverBaseUrl / companionService.baseUrl) that nothing forces to agree. Derive
them from serverHost:serverPort so the literal lives in ONE key — a box move = one
edit. Atlas's mirror-consistency lint already guards divergence; this removes the
duplication it guards.

## Definition of Done

- config.json server/companion base URLs derive from serverHost:serverPort (single source key); no duplicated host literal
- runtime consumers resolve the derived URL identically to before (no behavioral change)
- scripts/audit_address_mirrors.py + tests/lint/test_address_mirror_consistency.py pass
- validate_config.py passes; Typecheck passes; tests pass

## Validation Criteria

- (python validate_config.py) → (all pass)
- (pytest tests/lint/test_address_mirror_consistency.py -q) → (green)
- (grep config.json for the server IP literal) → (appears in exactly one key)

## Conditional Outcomes

- if a consumer reads a base-URL key that cannot be cleanly derived (offline route-probe hasRouteToServer is IP-route-based), keep that consumer's IP resolution + document why; do NOT fold the hostname-resolution design change (separate A-15 design story) into this de-dup

## Notes

Closes the structural duplication behind A-15; complements (does not replace)
Atlas's mirror-consistency lint, which stays as the divergence guard.
