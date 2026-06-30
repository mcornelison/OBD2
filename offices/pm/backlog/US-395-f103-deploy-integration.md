---
id: US-395
title: "F-103 deploy integration -- fold splash units into deploy-pi.sh + states-dir provisioning"
type: normal
parent: F-103
epicId: E-001
size: S
status: sprint-ready
sourceRefs: [F-103, prd-V0.29.2, iris-f103-spec-v1.2, atlas-c5-2026-06-29]
created: 2026-06-29
---

# US-395 — F-103 deploy integration (Iris US-C)

## Context

Folds the F-103 units into `deploy-pi.sh` so the splash ships with every Pi deploy,
and makes the deploy own the boot-durable `/run/eclipse-obd/states/` provisioning
(Atlas C-5). Depends on US-394. BENCH-ONLY validation.

## Goal

As the deploy path, I want F-103's units folded into `deploy-pi.sh` so the splash
ships with every Pi deploy.

## Definition of Done

- `deploy-pi.sh` installs + enables `eclipse-boot-state.service` + `eclipse-states-http.service` (sync-if-changed, mirroring the existing unit-install steps)
- `version.txt` written
- deploy **WARNs (not BLOCKs)** if splash assets are missing [A-9]
- **[ATLAS C-5 — deploy owns the states-dir provisioning]** `deploy-pi.sh` installs the provisioning mechanism that makes `/run/eclipse-obd/states/` exist at **every** boot (a `tmpfiles.d` entry or shared `RuntimeDirectory=eclipse-obd` on the F-103 units — **NOT** the existing deploy-time `install -d` alone, which tmpfs wipes on reboot)
- `specs/architecture.md` documents the `/run/eclipse-obd/states/` ownership + lifecycle across the `eclipse-obd` / `eclipse-boot-state` / `eclipse-states-http` units (one place; the multi-owner runtime dir is an SSOT-lifecycle contract)

## Validation Criteria (bench)

- (run `deploy-pi.sh`) → (the two F-103 units install + enable; re-run → no-op, sync-if-changed)
- (remove a splash asset + deploy) → (WARN emitted, deploy continues — not BLOCK)
- (after deploy, **cold reboot**) → (`/run/eclipse-obd/states/` is present + non-root-writable before any drive activity — the provisioning is boot-durable, not deploy-only)

## Conditional Outcomes

- if splash assets are missing at deploy time, WARN and continue — do NOT BLOCK the deploy [A-9]

## Notes

Build chain: US-393 → US-394 → **US-395** → US-396.
