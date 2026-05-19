# Finding: Power & Shutdown subsystem — documentation describes a system that no longer exists, and asserts one safety guarantee that is false

**Date**: 2026-05-18
**Author**: Atlas (Senior Solutions Architect)
**Severity**: High (one sub-item, F-6, is Critical — a documented load-bearing safety contract is false on the real hardware)
**Layer/Component**: Pi tier — power-source detection, shutdown decider, wake-on-power
**Grounded in**: code at branch `sprint/sprint38-bugfixes-V0.27.12`, hotfix commits `84b5469` + `4edbdc1`, deleted-ladder commit `9adb0fb`; not narrative.
**First task**: reconcile drift items A-1/A-2/A-3 from the Atlas onboarding watch list. Filed as findings + spec-correction spec; Ralph/PM action the edits (Atlas owns the architecture call; does not edit shared specs unilaterally pre-boundary-handoff).

---

## Summary

The Pi power/shutdown subsystem was re-architected in the V0.27 chain (Phase-2
power-watch, Sprints 37–38). The shutdown decider that every power doc
describes — the `PowerDownOrchestrator` staged VCELL ladder — **was deleted**
(`9adb0fb`). Its replacement (`eclipse-powerwatch`) is documented **nowhere in
`specs/` or `docs/`**. Separately, the power-source detection mechanism has had
**three incompatible generations** and the docs each freeze a different one.
Most seriously, the `Wake-on-Power EEPROM Contract` (architecture.md §11) and
the script `deploy-pi.sh` runs **on every deploy** assert a safety guarantee —
"auto-boots when wall power returns, no operator action" — that **Finding B
empirically proved false on the actual Pi 5 + X1209-HAT topology**. That false
guarantee is *why* the team believed unattended recovery was solved (US-253)
when it never was; it is the documentation root of the current chain blocker.

## Current reality (VERIFIED against code, this branch)

| Concern | What the code actually does now |
|---|---|
| Shutdown decider | `eclipse-powerwatch` systemd service (`deploy/eclipse-powerwatch.service` → `python -m src.pi.power.power_watch`), **isolated process**, **sole** decider. Legacy `PowerDownOrchestrator` ladder **deleted** `9adb0fb`. |
| Trigger signal | `PldSensor` (`src/pi/hardware/pld_sensor.py`) reading **X1209 BCM GPIO6** as deterministic "external power present" (`4edbdc1`). The VCELL-trend heuristic is **off the trigger path**. |
| Debounce | `PowerWatch` controller (`controller.py`) requires sustained on-battery across `confirmWindowSec` (re-sampled `confirmPollSec`) before any action; transient blip → abort, **no poweroff** (`84b5469`). |
| Boot-grace | power-loss ignored for `bootGraceSec` after service start (`__main__.py:266-292`). |
| Arm self-check | at startup GPIO6 must read power-present, else the service **refuses to arm** and stays up disarmed (`__main__.py:241-252`) — "uncertain → do NOT shut down", the deliberate inverse of the bricking fail-safe. |
| VCELL role | demoted to a **backstop only**, on a *successful* low read *after* sustained battery is confirmed; a failed read never powers off (`controller.py:130-146`). |
| Pre-shutdown work | bounded pipeline, one task today (`sync_with_server`, shutdown-type + WiFi-aware) under `totalWindowCapSec`, then graceful `systemctl poweroff`. |
| Config surface (new, undocumented) | `pi.powerWatch.{perTaskTimeoutSec, totalWindowCapSec, vcellFloorVolts, poweroffTimeoutSec, bootGraceSec, confirmWindowSec, confirmPollSec, pldGpioPin, pldPowerPresentHigh, pldPollSec}` |
| Deploy state | hotfixes committed on branch, **NOT deployed**; powerwatch masked-off on the Pi; GPIO6 polarity **unverified on the actual unit** (open). |

## Drift, per document (precise corrections)

### F-1 — `specs/architecture.md` §10.6 "Power-Down Orchestrator" (lines 1654-1693+) — STALE, describes deleted code
Documents the NORMAL→WARNING→IMMINENT→TRIGGER ladder at VCELL 3.70/3.55/3.45 V
as the live shutdown path. That code was deleted in `9adb0fb`.
**Correction**: replace §10.6 with a "Power-Watch (Phase-2)" section per
*Current reality* above. Retain the ladder narrative only as a clearly-marked
*superseded* design-history note (the VCELL-calibration lesson is still
valuable context). Add the `pi.powerWatch.*` config surface to §6.

### F-2 — `specs/architecture.md` §2 power-source detection (lines 95-131) — STALE, describes the mechanism that bricked the Pi
The MAX17048 VCELL-trend heuristic (3.95 V/30 s + −0.005 V/min slope) is
documented as the power-source decision path. This is exactly the signal whose
false-BATTERY-on-boot-sag **caused the 2026-05-18 bricking loop**, and it is no
longer the trigger.
**Correction**: state that the trigger is the X1209 GPIO6 PLD line
(`PldSensor`); the VCELL heuristic (`UpsMonitor.getPowerSource()`) is retained
only as backstop/telemetry, explicitly **not** the decision path. Cite the
bricking incident as the rationale.

### F-3 — `docs/hardware-reference.md` lines 93-129 — WRONG, describes an interface that does not exist
Describes an I2C "X1209 power-source register 0x08 (0=external,1=battery)".
architecture.md §2 itself states the MAX17048 has **no** AC-vs-battery sense
register and the X1209 regulates the rail identically in both modes. This
register map is fiction; reading it as a design reference is a trap.
**Correction**: delete the fictitious register-based power-source section;
point to the GPIO6 PLD design.

### F-4 — `docs/hardware-reference.md` lines 40-62 — ASSERTS unverified load-bearing hardware
States "Geekworm X1209 V1.0" + a telemetry register map **as fact**. The
bricking handoff §4 lists exact HAT model/vendor, whether a power-good pin is
broken out, and any auto-on register as **open questions to the CIO**.
`pld_sensor.py:1-11` is grounded only in Geekworm's *generic x120x* reference,
explicitly **not verified on this unit**. A spec asserting unverified
load-bearing hardware caused real design decisions to be built on sand.
**Correction**: demote to "believed X1209-class, UNVERIFIED" with an explicit
open-question callout; do not state a model/register map as fact until the CIO
confirms and GPIO6 polarity is bench-verified.

### F-5 — `README.md` line 7 — describes a different product
"Adafruit 1.3" 240×240 display … Gemma2/Qwen2.5". Actual: OSOYOO 3.5" 480×320
+ `llama3.1:8b` (architecture.md §2 lines 75-95). Low severity, but it is the
first file a newcomer reads.
**Correction**: one-line edit to match architecture.md §2.

### F-6 — `specs/architecture.md` §11 "Wake-on-Power EEPROM Contract" (lines 2125-2177) + `deploy/enforce-eeprom-power-off-on-halt.sh` — **CRITICAL: a documented safety guarantee that is FALSE on the real topology**
Both assert: `POWER_OFF_ON_HALT=0` ⇒ "PMIC stays awake watching power rails ⇒
**auto-boots when wall power returns ✅**, no operator action" — and
`deploy-pi.sh` **enforces this on every deploy** (`step_enforce_eeprom_power_off_on_halt`;
MEMORY.md records it observed rewriting the value 1→0 on the Pi, so the
enforcement is real and active).

**Finding B (empirical, chain-blocking) refutes the ✅ row for *this* hardware:**
after a graceful `poweroff`, the **X1209 HAT holds the Pi's 5 V rail up off
its battery**, so the Pi 5 PMIC **never sees a power-cycle edge** — the
documented "wall power returns → auto-boot" path **cannot physically fire**.
The §11 table describes **bare-Pi** behavior; the deployed system always has
the UPS HAT in the loop, which defeats it. This is not stale text — it is a
**load-bearing safety contract that is false as written**, and believing it
(US-253) is precisely why unattended in-car recovery was thought solved when
it never was. It is the documentation root of the current chain blocker.

Secondary inconsistency: §11 line 2140 claims the Pi's EEPROM line is
"absent → default 0" while the Finding-B record shows a 1→0 rewrite was
needed — the doc is also wrong about the Pi's *actual current* EEPROM state.

**Correction (do NOT just patch the table):** §11 must be rewritten to state
that on the Pi 5 + X1209-HAT topology `POWER_OFF_ON_HALT` is **necessary but
not sufficient** for unattended wake; the HAT-holds-the-rail constraint must
be documented as the governing fact; the real wake enabler (GPIO3-low / HAT
power-good→GPIO3 mod / a HAT auto-on register, per the handoff candidate
fixes) must be the documented contract once the CIO ratifies the approach.
Until then §11 must carry an explicit "**KNOWN FALSE on this topology — see
Finding B**" banner so no one builds on it again. This is the one item here
that should not wait for a routine spec pass.

## Impact

- The most safety-critical, most-churned subsystem has the least accurate
  documentation. Anyone (agent or human) trusting `specs/architecture.md`
  §10.6/§11 or `docs/hardware-reference.md` for the power path is reasoning
  about deleted code and a false wake guarantee.
- F-6 directly explains the chain blocker: US-253 "closed" the unattended-wake
  drill on paper via an EEPROM setting that cannot work behind the HAT. The
  doc manufactured false confidence.
- F-3/F-4 mean future power work risks repeating the GPIO6-style "grounded in
  a generic reference, unverified on the unit" mistake.

## Recommended action

1. **F-6 first, now**: banner §11 + the enforce script header as KNOWN-FALSE
   pending the ratified wake fix. This is a correctness/safety fix, not
   housekeeping. Route to PM/CIO as a blocker-class doc fix.
2. **F-1/F-2**: when Phase-2 power-watch reaches a non-failed deployed state,
   rewrite §10.6 (→ Power-Watch) and §2 (→ GPIO6 trigger) from the code, not
   the plan. Documenting a currently-bricking-and-masked subsystem as if it
   works would itself be drift — document the design **and its current FAILED
   status** explicitly.
3. **F-3/F-4**: correct `docs/hardware-reference.md` to remove fiction and
   mark the HAT identity UNVERIFIED with an open-question callout (ties to the
   CIO open questions already in the handoff).
4. **F-5**: trivial README one-liner.
5. **Architecture spec hygiene (structural, → tech debt)**: the architecture
   spec's mod-history stops at Sprint 21 while the system is at Sprint 38.
   Recommend a standing rule that any sprint touching a load-bearing subsystem
   updates its architecture.md section in the same sprint — enforced as part
   of the design gate Atlas now owns.

Atlas owns the architecture call on the corrected design; Ralph engineers any
code/script change; Marcus orchestrates the spec-edit work into a sprint/TD.
Coordinate F-6 framing with Tester (it intersects the chain-merge gate they
own the verdict on).
