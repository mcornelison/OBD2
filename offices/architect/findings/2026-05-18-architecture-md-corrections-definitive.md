# DEFINITIVE: architecture.md §2 / §10.6 / §11 correction targets (F-6 resolution / plan T9 DoD)

**Date:** 2026-05-18
**Author:** Atlas (Senior Solutions Architect) — this is the Atlas-owned architecture call
**Status:** DEFINITIVE. This file is the concrete target for plan **T9**. Marcus orchestrates it into the sprint DoD; Ralph implements the edits **in-sprint** (design-gate rule: load-bearing subsystem → spec corrected same sprint); Atlas gates the implementation against THIS text. Resolves findings **F-1, F-2, F-6** (and supports F-3/F-4 in `hardware-reference.md`).
**Honesty rule (the whole point of F-6):** the corrected text must NOT replace one false certainty with another. It states what is **known by evidence**, what is **empirically gated** (and by which gate), and what is the **arbiter**. An architect being definitive here means definitive about *structure and the known/measured boundary* — not asserting a wake mechanism we have not yet measured.

---

## §2 — Power-source detection — REPLACE the VCELL-heuristic narrative WITH:

> **Power-source detection (SSOT).** The power-source fact ("is external/USB-C
> power present?") has exactly one authoritative provider: `PowerSourceProvider`
> (`src/pi/power/power_source_provider.py`), which wraps the X1209 PLD line on
> **BCM GPIO 6, digital, HIGH = power present** (vendor-confirmed: Geekworm
> X1209 wiki "AC power loss … detection via GPIO" + Suptronics official
> `pld.py`; no I2C in this path). The UI and the ShutdownSequencer both consume
> this one provider and differ only by policy (UI = instantaneous; sequencer =
> 5 s smoothed).
>
> `UpsMonitor`/the MAX17048 fuel gauge provides **battery charge/health only**
> (VCELL volts, SOC). It is a *different fact* and is **not** a power-source
> signal. The former `UpsMonitor.getPowerSource()` VCELL-trend heuristic is
> **retired from the power-source path** — inferring power source from a charge
> *trend* caused the 2026-05-18 self-bricking loop (false BATTERY on the boot
> VCELL sag while external power was physically connected). Do not reintroduce
> any second power-source acquisition path (SSOT invariant; Atlas design gate).

## §10.6 — REPLACE "Power-Down Orchestrator" WITH "Shutdown Sequencer":

> **§10.6 Shutdown Sequencer.** The legacy `PowerDownOrchestrator` staged VCELL
> ladder (NORMAL→WARNING→IMMINENT→TRIGGER) was **deleted** (commit `9adb0fb`,
> Phase-2 T9). The sole shutdown decider is `ShutdownSequencer`
> (`src/pi/power/power_watch/controller.py`), an isolated systemd service
> (`eclipse-powerwatch`, separate failure domain from `eclipse-obd`).
>
> Flow: `PowerSourceProvider` reports power LOST → **5 s smoothing**
> (`pi.powerWatch.smoothingSec`, configurable; a single power-present read
> within the interval cancels — pure blip rejection; this is the safety
> property, shipped in V1) and **boot-grace** → arm-self-check (refuse to arm
> if GPIO6 does not read power-present at start) → a bounded pre-shutdown
> **window** of ordered `ShutdownTask`s (V1: exactly one, `SyncWithServerTask`;
> pluggable seam) → window exits on **all-tasks-terminal OR `windowCapSec`** →
> graceful `systemctl poweroff`. **Emergency:** a *successful* VCELL read ≤
> `vcellFloorVolts` short-circuits straight to poweroff; a *failed* VCELL read
> never powers off (uncertainty ≠ power loss).
>
> *Superseded design history (retained for the lesson, not as current
> behavior):* US-216/US-234's SOC%→VCELL ladder + the 40-pt MAX17048 SOC%
> calibration finding. The calibration lesson stands; the ladder as a shutdown
> mechanism does not.

## §11 — REPLACE "Wake-on-Power EEPROM Contract" WITH (this is the F-6 fix):

> **§11 Wake-on-Power — Pi 5 + X1209-HAT topology.** `POWER_OFF_ON_HALT=1`
> is the **locked setting** for this system (CIO decision 2026-05-18), enforced
> by `deploy/enforce-eeprom-power-off-on-halt.sh` (plan T8 corrects it to
> enforce `1`; the prior force-`0` was a defect that reverted the correct
> setting every deploy).
>
> Rationale (topology-specific): with the X1209 UPS HAT holding the Pi's 5 V
> rail up off its battery, `=0` leaves the PMIC active after `poweroff` and the
> PMIC **never sees a power-cycle edge** when external power returns → no
> unattended auto-boot (this is Finding B, observed empirically). `=1` powers
> the PMIC fully off so a USB-C power-return is a real boot event.
>
> **The previously documented "`=0` ⇒ auto-boots ✅ / `=1` ⇒ needs button ❌"
> table was FALSE for this topology** (it described a bare Pi 5 with no HAT)
> and was the documentation root of the chain blocker (finding F-6). It is
> removed, not patched.
>
> **Empirically gated (stated honestly, do not assert beyond evidence):** the
> exact wake mechanism at `=1` (whether the X1209 presents a true Pi 5 V rail
> power-cycle on external-power-return) is confirmed by the **T1 bench
> observation** and the **IRL acceptance gate** (5 consecutive clean unattended
> shutdown→restore cycles), not by this document or any datasheet. Until that
> gate passes, treat unattended in-car recovery as *designed-for and pending
> empirical confirmation*, never as "solved." The empirical bench/IRL result
> is the sole arbiter; no spec text or vendor doc overrides it.

---

## Scope boundary (honest — so nothing is assumed-closed)

THIS resolves F-1 (§10.6 stale), F-2 (§2 stale), **F-6 (§11 false contract)**.
It does **not** resolve **Finding A** (`CLEAN_COMPLETE` / boot-progress
instrument honesty) — that is a separate open item outside the Sequencer's
scope and must stay independently tracked. `hardware-reference.md` F-3
(fictitious I2C power-source register — delete) and F-4 (UPS-HAT identity:
now vendor-confirmed X1209-class; state "X1209, GPIO6 PLD vendor-confirmed,
physical-unit check per plan T1") fold into the same T9.

## Atlas sign-off

This is the definitive T9 target. Marcus: this is concrete enough to put in
the sprint DoD verbatim as the acceptance for the doc-correction task. Atlas
gates the in-sprint implementation against this file. No further "definitive
answer" is owed — proceed to contract.
