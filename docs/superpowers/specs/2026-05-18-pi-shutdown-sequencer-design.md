# Pi Shutdown Sequencer — Design Spec

**Date:** 2026-05-18
**Author:** Atlas (Senior Solutions Architect)
**Status:** Approved (CIO, 2026-05-18) — pending spec read-through, then implementation plan
**Supersedes the design intent of:** `2026-05-17-power-management-phase2-pre-shutdown-pipeline-design.md` and the `power_watch` trigger tangle (V0.27.10–.15)

---

## 1. Why this exists (retrospective, one paragraph)

A small feature consumed ~13 sprints (V0.27.2–.15) and near-bricked the Pi.
Root cause was not bugs — it was framing. The team treated a small feature as
a sophisticated power-management system, framed it **reactively** ("watch for a
power drop, then scramble"), reused a **UI-grade** signal as a **trigger-grade**
signal, and repeatedly shipped components that were written but never proven to
run **as actually wired** (V0.27.12 DOA import; the lying journal canary fixed
4×; US-331 false-passed synthetic tests). This design removes the framing
errors, not just the bugs.

## 2. Principle: Single Source of Truth (SSOT) — prototype here, carry project-wide

The defining design pattern, to be prototyped in this feature and adopted
project-wide:

- **One authoritative provider per *fact*.** Not three code paths each making
  a possibly-different system call for the same fact.
- **Consumers apply policy, never their own acquisition.** The UI and the
  shutdown trigger consume the *same* power-source provider; they differ only
  in the policy applied on top (the UI renders the instantaneous value and
  tolerates a blip; the trigger applies smoothing before acting).
- **Separate facts that were conflated.** "Am I on external power?" (power
  **source**) and "how much charge is left?" (battery **state**) are different
  facts with different providers. Inferring source from a charge *trend* (the
  VCELL-slope heuristic) was the original sin and is retired.

| Fact | Single authoritative provider | Consumers |
|---|---|---|
| Power source (external present / lost) | `PowerSourceProvider` (wraps the X1209 GPIO6 PLD line) | UI (instantaneous), ShutdownSequencer (smoothed) |
| Battery charge / health (VCELL volts, SOC) | MAX17048 reader (`UpsMonitor`/readers) | Option-B floor backstop, `battery_health_log` |

`UpsMonitor.getPowerSource()` (VCELL-trend) is **removed from the power-source
path entirely**. No second opinion exists to disagree with the SSOT.

## 3. Architecture

It is a **ShutdownSequencer**, not a PowerWatch. Detection is an input; the
feature is an ordered, bounded shutdown sequence.

```
PowerSourceProvider (SSOT — GPIO6 PLD; ONLY power-source acquisition site)
   exposes: isExternalPowerPresent()  + startupArmCheck()
   ├──────────► UI consumer        (instantaneous, tolerant — behavior unchanged)
   └──────────► ShutdownSequencer  (trigger-grade policy)
        source → LOST, sustained ≥ smoothingSec (blip rejected); after bootGraceSec
        ▼
   ┌─ SHUTDOWN WINDOW ───────────────────────────────────────────┐
   │  ordered ShutdownTask list — each: bounded · idempotent ·    │
   │  isolated · best-effort (one task failing NEVER blocks       │
   │  poweroff)                                                   │
   │    1. SyncTask  — home wifi + DB server reachable? push;     │
   │                   not reachable → skip (no retry storm)      │
   │    [plugin seam: future tasks register; sequencer unchanged] │
   │  exit when: all tasks terminal  OR  windowCapSec elapsed     │
   │  emergency: a SUCCESSFUL VCELL read ≤ vcellFloorVolts        │
   │             short-circuits straight to poweroff (Option B)   │
   └───────────────────────────┬──────────────────────────────────┘
                               ▼
                  graceful  systemctl poweroff  (bounded by poweroffTimeoutSec)
                               │
       EEPROM POWER_OFF_ON_HALT=1 → full power-down → clean restore on next power
```

### Components (one job each, independently testable)

- **`PowerSourceProvider`** — SSOT for power source. Wraps the GPIO6 PLD line
  and the **arm self-check**: at service start GPIO6 MUST read power-present
  (the Pi only booted because power is live); if it cannot, the sequencer
  **refuses to arm** and stays up disarmed — the deliberate "uncertain ⇒ do
  NOT shut down" direction. Reuses the sound `PldSensor` (`4edbdc1`).
- **`ShutdownSequencer`** — owns trigger policy (smoothing, boot-grace) and
  the bounded window. Knows nothing about how power is read or what tasks do.
- **`ShutdownTask` interface + `SyncTask`** — the plugin seam. V1 ships
  exactly one task. Adding update-check later = implement the interface +
  register; **zero sequencer changes**.

### Trigger policy (the "trigger-grade" treatment)

1. **Boot-grace:** ignore power-loss for `bootGraceSec` after service start.
2. **Smoothing:** a LOST reading must hold continuously for `smoothingSec`
   (default **5 s**, configurable) before the shutdown window opens. A single
   power-present reading at any point *within the smoothing interval* cancels
   the confirm → no window, no poweroff (pure blip rejection). This safety
   property is **in V1**, not deferred (deferring it reships the bricking
   failure mode).
3. **Power-return abort:** if the source reads present *after* the window has
   opened (during task execution), abort the window and resume normal
   operation — no poweroff.

### Window bounding (Option B, locked)

- Exit on **all tasks terminal** OR **`windowCapSec`** elapsed → graceful
  poweroff.
- **Emergency short-circuit:** a *successful* VCELL read ≤ `vcellFloorVolts`
  → skip remaining tasks, poweroff now. A *failed* VCELL read never triggers
  poweroff (uncertainty ≠ power loss).

### Scope (Option A, locked)

V1 ships the sequencer scaffold + `PowerSourceProvider` + the `ShutdownTask`
interface + exactly one task (`SyncTask`). Update-check / download-while-
powered / staged apply-decision is the **first additive plugin in a later,
separate change** — and doubles as the proof the seam works. Not built now.

## 4. Configuration surface (zero magic numbers)

Every tunable is a validated config parameter (extends the existing validated
`pi.powerWatch.*` pattern; exact key namespace finalized in the plan):

| Param | Default | Purpose |
|---|---|---|
| `smoothingSec` | 5 | sustained-confirm window; blip rejection |
| `bootGraceSec` | 120 | ignore power-loss this long after service start |
| `windowCapSec` | 45 | hard cap on the task window → poweroff |
| `vcellFloorVolts` | 3.50 | Option-B emergency short-circuit (successful low read only) |
| `perTaskTimeoutSec` | 20 | per-task bound inside the window |
| `poweroffTimeoutSec` | 30 | bound on the poweroff call |
| `pldGpioPin` | 6 | SSOT hardware line (BCM) |
| `pldPowerPresentHigh` | true | polarity (set by the one-time bench verification) |

Defaults are conservative-interim; empirical battery-runtime tuning of the
window/cap is a config-only follow-up (no code change), owned by Spool.

## 5. Orchestration-proof (non-negotiable)

Addresses the recurring "written but never ran as wired" failure class:

- **Systemd-parity test:** one test invokes the entrypoint EXACTLY as systemd
  does — real `python -m <entrypoint>` under the unit's real `PYTHONPATH` —
  exercising the real import/component graph (I/O seams stubbed only at the
  hardware/network/poweroff boundary). Formalizes the existing
  `PW_TEST_ONESHOT` instinct as the gate.
- **Positive-evidence rule:** every component proves it executed by emitting
  positive evidence of execution. Absence of an error is never accepted as
  proof a step ran. (Project-wide rule, prototyped here; ties to the
  Atlas-owned design gate.)

## 6. Regression-first step (before building)

The CIO states the shutdown→restore loop **worked ~2 sprints back** with
`POWER_OFF_ON_HALT=1`. That is the strongest evidence available. Before
building, a short bisect confirms what regressed between that working state
and now. Output: a one-page "what regressed" note. This may shrink the build
and de-risks by anchoring on proven ground rather than re-deriving theory.

**Bundled bench observation (same session as the GPIO6 polarity check):**
with `POWER_OFF_ON_HALT=1`, when external/USB-C power returns after a graceful
poweroff, confirm empirically whether the X1209 presents a real Pi 5 V rail
power-cycle (clean PMIC cold-boot — explains "=1 worked") or keeps holding the
rail (would mean `=1` alone needs a GPIO3/button wake assist). This closes the
last wake-mechanism unknown by measurement, not theory — before any redeploy.

## 7. Retire vs keep (explicit)

- **Retire:** the `power_watch` power-source trigger tangle; the
  VCELL-heuristic-as-power-source path; the journal-scan boot canary.
- **Keep:** `PldSensor` + arm-self-check (sound); `UpsMonitor`/`PowerMonitor`
  as **battery-health + UI plumbing only** (power-source role deleted);
  `eclipse-powerwatch`-style isolated-service topology (separate failure
  domain from `eclipse-obd` — this part of Phase-2 was correct).

## 8. Dependencies, risks, open items

1. **GPIO6 PLD — VENDOR-CONFIRMED for the X1209; residual = a 30-second
   physical sanity check (downgraded from "unknown" 2026-05-18).** Geekworm's
   own X1209 wiki lists "AC power loss and power adapter failure detection via
   GPIO" as an X1209 feature; Suptronics' official `pld.py` for this board
   family reads it as **digital BCM GPIO 6, HIGH = power present** (`pld_state
   == 1` = "AC Power OK"), no I2C — matching the shipped `pldGpioPin=6 /
   pldPowerPresentHigh=true`. The MAX17048 (I2C fuel gauge) is a *different
   fact* and is explicitly NOT this signal. Remaining check is a one-time
   read-only watch on the physical unit using **our** `PldSensor` (no
   poweroff, binary: word flips on unplug/replug or it doesn't) — a hard gate
   before IRL but no longer a design risk. The arm-self-check still makes a
   wrong pin/polarity fail safe (refuse-to-arm), not catastrophic.
   *Robustness note:* the vendor reference hardcodes the gpiochip and broke
   across the kernel 6.6.45 `gpiochip4`→`gpiochip0` rename; our `PldSensor`
   uses `gpiozero` which auto-resolves the chip — keep it that way, do not
   reintroduce a hardcoded gpiochip.
2. **EEPROM — DECISION LOCKED `POWER_OFF_ON_HALT=1` (CIO 2026-05-18).**
   Rationale: on the Pi 5 + X1209-HAT topology, `=1` fully powers the PMIC
   off so a USB-C power-return is a real boot event; `=0` leaves the PMIC
   active while the HAT holds the rail → no clean off→on edge → no auto-boot
   (= Finding B). Backed by two independent data points (CIO observed `=1`
   working; Finding B observed `=0` failing). **`deploy/enforce-eeprom-power-off-on-halt.sh`
   currently force-reverts to `0` on EVERY deploy — it is now an in-scope
   defect**: the plan must fix/retire it so deploy stops fighting the locked
   setting (an orchestration-integrity defect in its own right). The
   documented EEPROM contract (`architecture.md` §11) is KNOWN-UNRELIABLE
   (finding F-6), describes bare-Pi (no-HAT) behavior, and MUST NOT be used to
   reason about wake; the empirical bench/IRL result is the only arbiter.
3. **`architecture.md` §10.6/§11 + `hardware-reference.md`** remain drifted
   (findings F-1..F-6). Updating the power section per the new design is in
   scope of the design-gate rule (same-sprint spec update for load-bearing
   subsystems).

## 9. Non-goals (YAGNI)

- No update-check / OTA in V1 (Option A).
- No new power-source detection cleverness — GPIO6 PLD only.
- No battery-level-driven *trigger* — VCELL is a backstop only.
- No redesign of the UI power indicator (it stays; it just consumes the SSOT).
- No ECMLink / non-power scope.

## 10. Success criteria & acceptance gates

1. **One power-source acquisition site** in the codebase (SSOT verified by
   audit; the VCELL-heuristic source path is gone).
2. **Systemd-parity test green** — entrypoint runs as wired.
3. **Bench drill:** boot N times on external power → Pi stays up
   > bootGrace + smoothing, never self-powers-off (the precondition the
   bricking incident proves is mandatory) — THEN on-battery cycles:
   battery-detected → window runs (sync when reachable; skip when not) →
   graceful poweroff → **unattended restore on next power** (Spool-proposed
   acceptance: 5 consecutive clean unattended cycles; CIO ratifies the count).
4. Regression note produced and reconciled.
5. No magic numbers — every tunable is a validated config param.

## 11. Decisions locked (audit trail)

| Decision | Choice | By |
|---|---|---|
| Window bounding | Option B (tasks-or-cap + successful-low-VCELL emergency) | CIO 2026-05-18 |
| V1 scope | Option A (sync-only + extensible plugin seam) | CIO 2026-05-18 |
| Trigger source | Approach 1 (GPIO6 PLD ground-truth SSOT) | CIO 2026-05-18 |
| Smoothing | 5 s, configurable, **in V1** (safety property, not deferrable) | Atlas rec, CIO confirmed |
| SSOT pattern | One provider per fact; consumers apply policy; carry project-wide | CIO 2026-05-18 |
| `POWER_OFF_ON_HALT` | **`=1` locked**; enforce-script force-`0` is an in-scope defect; doc §11 is unreliable, empirical drill is arbiter | CIO 2026-05-18 |
