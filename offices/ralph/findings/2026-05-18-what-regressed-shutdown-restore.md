# What Regressed: Shutdown→Restore Loop (regression-first note)

**Plan Task 1, Step 3** — `docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md`
**Author:** Ralph · **Date:** 2026-05-18 · **Branch:** `sprint/sprint39-bugfixes-V0.27.15`
**Status:** evidence-grounded; every claim cites a commit/line. No speculation. Open questions are routed to the bench checklist, not guessed.

---

## Method note (anchor reinterpretation — flagged, not silently changed)

Plan Step 2 prescribes `git diff <V0.27.12-tip>..HEAD -- power_watch/__main__.py controller.py enforce-eeprom-power-off-on-halt.sh`. Git ground-truth shows this anchor needs reinterpreting, and here is why (so Atlas can sanity-check the substitution):

- `git ls-tree -r 9060b75 -- src/pi/power/` (V0.27.12) → **`power_watch/` absent**.
- `git ls-tree -r d049e30 -- src/pi/power/power_watch/` (V0.27.13) → **absent**.
- `git ls-tree -r 0125417 -- src/pi/power/power_watch/` (V0.27.14) → **present (full module)**.

So a `V0.27.12..HEAD` diff of those `.py` files is an all-additions blob (uninformative), and the EEPROM-script half of that diff is **empty**: `git diff --stat 9060b75..HEAD -- deploy/enforce-eeprom-power-off-on-halt.sh` → no output (file unchanged across the entire range). The substantive regression boundary is therefore **V0.27.13 (`d049e30`) → V0.27.14 (`0125417`)** for the trigger, and the EEPROM script is a *pre-existing* latent issue, not a range regression. The plan's intent ("diff the trigger + EEPROM path across the regression range") is fully served by the correct anchors below.

## Version → commit map (from `deploy/RELEASE_VERSION` history)

| Version | Bump commit | `power_watch/` present? | Shutdown decider |
|---|---|---|---|
| V0.27.12 | `9060b75` | No | legacy `PowerDownOrchestrator` ladder (`src/pi/power/orchestrator.py`) |
| V0.27.13 | `d049e30` | No | legacy ladder (DOA import hotfix only) |
| **V0.27.14** | **`0125417`** | **Yes** | **new `power_watch` controller — bricking deploy** |
| V0.27.15 (this branch) | _unbumped_ | Yes | `power_watch` + hotfixes `84b5469`, `4edbdc1` |

---

## (a) The single regression that broke the working loop

**V0.27.14 (`0125417`) swapped the shutdown decider in one release and wired the new trigger to a UI-grade signal.**

Two changes landed together between `d049e30` (V0.27.13) and `0125417` (V0.27.14):

1. **`9adb0fb`** — `refactor(power): delete legacy PowerDownOrchestrator ladder; eclipse-powerwatch is sole shutdown decider`. Removed `src/pi/power/orchestrator.py` (−1230 LOC) plus ~10,829 deletions across `hardware_manager.py`, `lifecycle.py`, and 25 test files. The mechanism that handled shutdown→restore at V0.27.12/.13 was deleted.
2. The new `power_watch` controller became sole decider with its trigger fed by the **`UpsMonitor.getPowerSource()` VCELL-trend heuristic**. At the bricking deploy, `git show 0125417:src/pi/power/power_watch/__main__.py`:
   - `:103-122` `_buildIsOnBattery(monitor)` → `isOnBattery()` returns `monitor.getPowerSource() == PowerSource.BATTERY`
   - `:227-229` production `PowerWatch(isOnBattery=_buildIsOnBattery(monitor), vcell=monitor.getVcell, …)`

`getPowerSource()` is a charge-*trend* heuristic (spec §2 "the original sin"). It returns `BATTERY` on a transient VCELL sag — e.g. boot inrush — so on **every boot** the controller saw `BATTERY` → opened the shutdown path → `systemctl poweroff` → power-cycle → boot-sag again → **self-poweroff loop = brick**, even on external power. This matches the recorded IRL failure (MEMORY: "trigger acted on the VCELL-trend heuristic's first unconfirmed BATTERY at boot-sag").

**Net:** the regression is not a line bug — it is *replacing a working ladder with a new decider whose trigger reads a UI-grade trend signal as if it were power-source ground truth*, shipped as a single release with no smoothing/boot-grace on that trigger.

### Not the regression (ruled out by evidence)

- **`deploy/enforce-eeprom-power-off-on-halt.sh`** — `git log --follow` shows exactly one commit: `56c47c9` (Sprint 21); **never modified since**. `git diff --stat 9060b75..HEAD` on it = empty. It is **not a range regression.** It *is* a pre-existing latent inversion: its header (lines 5–17) and logic (lines 25–27, 77, 85) enforce `POWER_OFF_ON_HALT=0` on every deploy, asserting `=0` keeps the PMIC watching the rails for auto-wake. The CIO-locked decision (2026-05-18) is the **opposite** for the Pi 5 + X1209-HAT topology (`=1`; spec §8.2 / §11): `=0` leaves the PMIC active while the HAT holds the 5 V rail → no off→on edge → no auto-boot (Finding B). The script *actively fights the locked `=1`* on every deploy. Long-standing defect, correctly scoped as plan **Task 8**, not Task 1's regression.

---

## (b) Does the clean target design already subsume it?

**Yes — fully.** Spec `2026-05-18-pi-shutdown-sequencer-design.md`:

- **§2 SSOT / Task 4** — `UpsMonitor.getPowerSource()` is removed from the power-source path entirely; the VCELL-trend trigger (the exact regression) cannot be reintroduced. No second opinion exists.
- **§3 trigger policy / Task 5** — trigger comes from `PowerSourceProvider` over GPIO6 PLD ground-truth, with **bootGrace** + **5 s smoothing** (blip rejection). This rejects precisely the boot-sag transient that caused the loop. Smoothing is in V1 (§11, non-deferrable).
- **Already partly in tree on this branch:** hotfix `4edbdc1` already moved the trigger off the heuristic — `git show HEAD:…/__main__.py` shows `:217 isOnBattery=pld.isPowerLost`, `:200 PldSensor(...)`, `:241 pld.startupPolarityOk()` arm-check, `:271-279` bootGrace loop; `getPowerSource` no longer appears in `__main__.py`. Hotfix `84b5469` added debounce + boot-grace + reversed uncertain-VCELL. The clean design **formalizes and keeps** these (plan Task 5 explicitly reuses `84b5469`'s debounce logic and renames `PowerWatch`→`ShutdownSequencer`).
- **EEPROM defect** subsumed by **Task 8** (flip script to `=1`) + **Task 9** (doc reconciliation §11).

The build does not need to re-derive anything; it consolidates a fix that is already directionally in tree behind the SSOT design.

---

## (c) Behavior from the working version worth preserving

1. **Isolated-service topology** — `eclipse-powerwatch` as a separate failure domain from `eclipse-obd` (spec §7 "keep"; this part of Phase-2 was correct).
2. **`PldSensor` + arm-self-check** — sound; from hotfix `4edbdc1` (`__main__.py:241 startupPolarityOk`). Spec §7 keep; plan Task 3 wraps it in `PowerSourceProvider`.
3. **Bounded controller / pipeline / outcome / `SyncWithServerTask`** — sound; plan Architecture says reuse as-is (do not rebuild).
4. **Debounce + boot-grace from `84b5469`** — plan Task 5 Step 3 explicitly keeps the logic (rename only).
5. **`gpiozero`-based chip auto-resolution in `PldSensor`** — spec §8.1: do NOT reintroduce a hardcoded `gpiochip` (the vendor `pld.py` broke on the kernel 6.6.45 `gpiochip4`→`gpiochip0` rename).

---

## Open question — routed to the bench checklist, NOT guessed

The CIO states shutdown→restore "worked ~2 sprints back with `POWER_OFF_ON_HALT=1`." Recorded evidence shows a tension to resolve empirically, not by assertion:

- Git proves the working decider at V0.27.12/.13 was the **legacy ladder**, and the EEPROM script has *enforced `=0` since Sprint 21* — so if `=1` was ever observed in the EEPROM at a "working" point, it was set out-of-band (not by deploy), or the working observation predates the X1209-HAT install / a different EEPROM state.
- MEMORY records the V0.27.13 bench drill **Finding B** = "no unattended auto-recovery; HAT holds the 5 V rail at `=0`".

Both can be true. The `=1`-vs-`=0` wake mechanism on *this physical unit + HAT* is a measurement, not a deduction. **Resolved by Bench Check B** in the companion checklist (mandated by spec §6 and plan Task 1 Step 4). This note makes no claim about the wake mechanism; the bench result is the only arbiter (spec §8.2).

---

## One-line summary

The working shutdown→restore loop broke at **V0.27.14 (`0125417`)** when `9adb0fb` deleted the legacy `PowerDownOrchestrator` ladder and made the new `power_watch` controller sole decider with its trigger wired to the `UpsMonitor.getPowerSource()` VCELL-trend heuristic, which self-triggers on boot-sag → self-poweroff brick loop. The ShutdownSequencer design (GPIO6 SSOT + bootGrace + 5 s smoothing, Tasks 3–5) fully subsumes the fix; the EEPROM `=0`-forcing script is a *separate* pre-existing inversion correctly scoped as Task 8; the `=1` wake mechanism is deferred to empirical Bench Check B.
