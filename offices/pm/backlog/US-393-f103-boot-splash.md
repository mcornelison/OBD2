---
id: US-393
title: "F-103 boot splash -- chromium kiosk + localhost state server on the 3.5\" display"
type: normal
parent: F-103
epicId: E-001
size: M
status: sprint-ready
sourceRefs: [F-103, prd-V0.29.2, iris-f103-spec-v1.2, atlas-c5-2026-06-29]
created: 2026-06-29
---

# US-393 — F-103 boot splash (Iris US-A)

## Context

The boot splash is the **required-first runtime** the rest of the Pi UI line
(carousel, DTC viewer) depends on — it must land before any of that can be built
(Atlas condition C-1). Backed by a chromium kiosk + a localhost state server on the
3.5" display. Iris spec v1.2 (Atlas-gated 2026-06-05);
`docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` §9 is the
source for the validationCriteria. BENCH-ONLY validation (CIO waived drive
requirements 2026-06-29); the Pi is on wall power.

## Goal

As the Pi at boot, I want a branded boot splash on the 3.5" display backed by a
chromium kiosk + a localhost state server, so the operator sees boot progress
instead of a console/blank screen.

## Definition of Done

- chromium kiosk launches on boot rendering the splash on the 3.5" display
- new `eclipse-boot-state.service` emits boot phases [A-1]
- new `eclipse-states-http.service` serves state on `localhost:9899` with token auth (token SSOT, one source)
- splash reflects the eclipse-obd 3-tier health (T1/T2=degraded, T3 engine-off=informational per Spool S-1/S-2) + `HEALTHY_YIELD`
- retry-once on transient display/IPC failure
- **Rule-10:** the state-server + emitters land with matching `specs/architecture.md` + `specs/UI/` updates in-sprint
- **[ATLAS C-5 — states-dir boot provisioning]** `/run/eclipse-obd/states/` must exist at boot **independent of** `eclipse-obd.service` (that unit only creates `/run/eclipse-obd` via `RuntimeDirectory=eclipse-obd` on its own start, removes it on stop, and does **not** create the `states/` subdir): the F-103 emitter + HTTP server provision the dir themselves — each F-103 unit shares `RuntimeDirectory=eclipse-obd` (systemd ref-counts a shared name) **or** a `tmpfiles.d` entry creates `/run/eclipse-obd/states/` (owned non-root `mcornelison`) at boot — and the chosen mechanism is reconciled with eclipse-obd.service's remove-on-stop so the two do not fight (no `tmpfiles.d` exists today; the deploy-time `install -d` is wiped on every reboot)

## Validation Criteria (bench/boot drill)

- (**cold reboot** — power-cycle, NOT a warm restart with eclipse-obd already up) → (splash renders on the 3.5" display within the spec's boot-grace window, not console/blank; proves `/run/eclipse-obd/states/` exists at boot without eclipse-obd having provisioned it — a warm bench where the dir already exists is insufficient)
- (`curl -H <token> localhost:9899/...`) → (returns the current boot state JSON)
- (feed a synthetic boot-phase sequence) → (splash transitions through the phases — spec §9 synthetic criteria)

## Conditional Outcomes

- if HDMI/display isn't ready at boot, retry-once then degrade gracefully (no crash, no boot stall)

## Notes

Build chain: **US-393 → US-394 → US-395 → US-396** (F-103 is sequential — the boot
runtime underpins shutdown, deploy, defects). Atlas owns the UI architecture gate;
Iris owns the splash design.
