# V0.30 boot + shutdown sequence — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming
**Storyboard:** `proposals/2026-10-13-v030-boot-shutdown.html` → https://claude.ai/artifact/HfQ1QVUq7N9EbBunrSF4hi (logo is a placeholder; the real splash keeps its existing logo asset)
**DoD lines served:** 11 (boot: driving warning → logo → ends when actually collecting, real readiness signals; shutdown: sync bar from the real backlog that looks stalled when stalled), 1 (the boot metric's phases)
**Stories:** US-785 (warning screen) · US-869 (sequencing) · US-870 (sync bar) · F-103 (splash) · relates to US-858/859/866 (OS boot path), US-649..652 (DRM kiosk)
**Style:** 90s Mitsubishi OEM (`v030-frame-and-style-design.md`)
**Reworked 2026-10-13:** Atlas's rulings (B-1..B-3, S-1..S-4) and his renames: readiness is a feed's **first live sample**, not its first database row.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Boot sequence (CIO, verbatim in substance)
> *"Show this warning while the Pi boots up. This should be the first thing I see and I never see the Linux text bootup process. Then when the OS is done booting, our software starts to boot. This is when the rotating animation happens. The first spin always does 1 spin. The 2nd brighter spin keeps spinning while our code boots; when everything is ready the last brightest logo spin happens, then I see our dashboard."*

| Phase | Runs | On the glass |
|---|---|---|
| **0 · Power-on → OS boot** | firmware, kernel, OS (**before any of our code**) | **WARNING image**: `WARNING` (`--critical-red` title) + `Keep your eyes on the road. / Do not operate this display while driving.` **No firmware rainbow, no Linux text, ever.** |
| **1 · Our software starts** | splash service | **Spin 1: exactly one rotation, dimmest** |
| **2 · Our code boots** | services, OBD connect, sensors | **Spin 2: brighter, loops**, + **4-feed checklist** `OBD · IMU · LIGHT · UPS`, each ticking `✓` when **its first live sample arrives** (R3; `capture-health.feeds.<feed>.firstSampleTs`) |
| **3 · Ready** | OBD has its first sample, **or** IMU + LIGHT + UPS are ready **and the ceiling passed** | **Spin 3: brightest, one rotation**, then the **Driving page** |

### 1.1 Rules
- **No touch at any point** (R5): the warning has **no OK button** (the Pioneer reference's button is dropped).
- **Phase 0 is an OS boot-screen job**, not the kiosk's: **Plymouth**, already installed and enabled on the Pi (Atlas B-1, MEASURED). Remaining work: a Plymouth theme with Iris's 480×320 image; `disable_splash=1` (the rainbow); cmdline `loglevel=3 vt.global_cursor_default=0` and no `console=tty1` text; hand-off by `plymouth quit --retain-splash`, with the kiosk unit ordered `After=` plymouth-quit (both want KMS master under DRM). Deploy-managed, reversible, and **proved on a cold key-on with SSH verified before and after**. **Owner: Atlas/Ralph, in the DRM slice** (US-649 order), not the UI stories. Iris supplies the image.
- **Phase 1 starts on `boot-state.healthy`** (US-494 = Pi core up; Atlas B-2).
- **Checklist ticks come from real readiness signals**: each feed's **first live sample this eclipse-obd process**, `capture-health.feeds.<feed>.firstSampleTs` (Atlas, renamed 2026-10-13; one producer, also used by System, DoD 1 and Warnings DATA). Never a timer, never a database row (DoD 11; US-869 floor/ceiling shape in `specs/design-patterns.md`). A process restart re-arms it, so the checklist can honestly run again.
- **Ceiling (ECU never answers, e.g. key in ACC or the ARCH-061 fault):** once IMU, LIGHT and UPS are ready and the ceiling passes, spin 3 **still plays**, with `OBD · waiting for ECU` visible during it, then the dashboard opens with the link chain **grey at ECU**. Spin 3 means *"the software is ready"*, not *"everything is connected"*. Key **`pi.display.boot.handoffCeilingSec`** = null until the DoD 1 baseline (R4); no number here.
- Spin-2 floor: at least one full rotation (no flicker-through on a fast boot).
- `prefers-reduced-motion`: spins become brightness steps without rotation.

## 2. Shutdown sequence (CIO)
> *"Show a progress bar 0-25-50-75-100 %. Away from home the progress bar is quick and represents the soft shutdown progress. At home it is the data sync + the soft shutdown progress. The middle spinning logo will always spin once but can spin more if there is < 100 % of the progress meter. Always one last spin of the dim logo and the close-out animation, then fade to black and then off."*

| Step | On the glass |
|---|---|
| Key off | logo, **reverse spin** (≥ 1 rotation; keeps spinning while the bar < 100 %) + **progress bar** with ticks `0 · 25 · 50 · 75 · 100 %` + a label naming the current part |
| **At home** | **0–75 % = sync**: rows the server **confirmed** ÷ rows waiting at key-off (US-776-i post-commit stored count; "100 %" means server-confirmed, never "sent") · **75–100 % = soft-shutdown steps**. A marker at 75 %. |
| **Away** | `away from home · not syncing · shutting down`; **0–100 % = soft-shutdown steps only** (quick). Never a 0 % sync bar (F-155 at-home sync). |
| **Sync stall** | bar **amber**, label `sync stalled · n rows kept for next time`; when the provider reports the stall it **moves on** to the shutdown quarter. Unsent rows stay queued. **No new timeout:** the drain's existing `stallSec` (60 s) is the one number (Atlas S-2; the UPS is not the binding limit). |
| Close-out | one last **dim** spin + close-out animation → **fade to black** → power off |
| **Key back on** | shutdown **cancels** (`shutdown-state.phase: cancelled` exists), the bar disappears, the **dashboard returns** without a reboot |

### 2.1 Rules
- **Every percentage comes from a real stage**: confirmed rows, or completed shutdown steps. Never a timer, never an estimate. A stall **looks** stalled (US-795 wording).
- The shutdown page renders on **splash-grace**. It is **already not shed** (Atlas S-4: `DEFAULT_SHED_UNITS` = `("eclipse-dashboard",)`); keep it so.
- STOP-level power faults are not this page's job (System/Warnings).

## 3. Data contract

| Need | Status | Owner |
|---|---|---|
| OS boot splash (phase 0): Plymouth theme + `disable_splash=1` + quiet cmdline + `--retain-splash` hand-off | Plymouth installed; **theme + config new**, DRM slice | Atlas/Ralph |
| Phase 1 trigger: `boot-state.healthy` | exists (US-494) | — |
| Per-feed readiness: `capture-health.feeds.<feed>.{state, firstSampleTs, lastSampleSecondsAgo}` | **in Sprint 98** (US-873) | Atlas · Ralph |
| Boot ceiling: `pi.display.boot.handoffCeilingSec` | key named; value null until the DoD 1 baseline | CIO + Atlas |
| Shutdown: `shutdown-state.step{index, of, name}` + `sync{waitingAtKeyOff, confirmed}` (0–75 % uses `confirmed`, never "sent") | **new** (Atlas S-1) | Atlas |
| Sync stall | existing drain `stallSec` = 60 | exists |
| Key-back-on: `phase: cancelled` → splash hands back | exists; **page hand-back new** | Ralph |

## 4. Acceptance criteria (draft)
1. **Key-on from fully off, n ≥ 5:** the first pixels are the WARNING image; **no firmware rainbow and no Linux text** appear at any frame (phone video, the DoD 1 method).
2. Spin 1 completes exactly one rotation; spin 2 loops until ready; spin 3 completes exactly one rotation, then the Driving page.
3. Each checklist item ticks only when its feed's `firstSampleTs` is non-null (fixture: hold one feed's `firstSampleTs` null; its tick waits; a `restart-rearmed` fixture un-ticks it).
4. ECU-silent fixture: hand-off at the ceiling; `OBD · waiting for ECU` shown during spin 3; dashboard link chain grey at ECU.
5. Home shutdown fixture: bar ≤ 75 % until the server confirms all rows; label says sync; then shutdown steps to 100 %.
6. Away fixture: no sync segment; label says not syncing; bar is step-driven.
7. Stall fixture: bar amber + `n rows kept for next time`; shutdown proceeds when the provider reports the stall; rows remain queued (verified next sync).
8. Key-back-on fixture: shutdown cancels and the dashboard returns without a reboot.
9. No literal colour or px in splash CSS.
10. **DoD (R15): CIO in the car, key-on and key-off.**

## 5. Out of scope
The boot-time target itself (R4: set by the CIO after the baseline) · OS boot-speed work (US-858/859/866; this spec only needs their splash hook) · lighter renderer (US-867, research only).
