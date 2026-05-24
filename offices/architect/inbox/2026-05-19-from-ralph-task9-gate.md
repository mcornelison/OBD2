From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 9 complete. Design-gate (Rule 10) requested.**

Same-sprint architecture.md + hardware-reference.md reconciliation per
your DEFINITIVE corrections file. F-1, F-2, F-3, F-4, F-6 all closed.
F-5 (README) left out of scope per the plan / your literal direction.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`c73ea91`** (2 files,
**+178 / −312**; the negative delta is the deleted-orchestrator ladder body):

- `specs/architecture.md` — §2 power-source detection rewritten (SSOT
  narrative); §10.6 Power-Down Orchestrator → ShutdownSequencer (with the
  calibration lesson retained as a condensed note pointing to git history
  for the deleted ladder body); §11 Wake-on-Power → Pi 5 + X1209-HAT
  topology with empirical-gated honesty; "Last Updated" set to SS-T9.
- `docs/hardware-reference.md` — HAT identity vendor-confirmed +
  Bench-Check-A PASS; fictitious `0x08 Power Source` I2C register deleted
  from the MAX17048 telemetry table + example code; Power Loss Detection
  section repointed to GPIO 6 PLD `PowerSourceProvider` SSOT; mod-history
  row added.

## BEFORE / AFTER excerpts (Atlas criterion #1)

### §2 power-source detection

**BEFORE (the F-2 VCELL-heuristic narrative):**
> The MAX17048 fuel gauge has no AC-vs-battery sense register … `UpsMonitor.getPowerSource()`
> consumes two VCELL-only rules over a rolling 60 s history buffer: Sustained-threshold
> rule (primary, US-235) … Slope rule (tuned secondary, US-235) … Either rule firing
> returns BATTERY.

**AFTER (verbatim-equivalent to corrections-definitive §2):**
> **Power-source detection (SSOT).** The power-source fact ("is external/USB-C
> power present?") has exactly one authoritative provider: `PowerSourceProvider`
> … which wraps the X1209 PLD line on **BCM GPIO 6, digital, HIGH = power present**
> (vendor-confirmed: Geekworm X1209 wiki + Suptronics official `pld.py`; no I2C in
> this path). … `UpsMonitor` / the MAX17048 fuel gauge provides **battery
> charge/health only** … The former `UpsMonitor.getPowerSource()` VCELL-trend
> heuristic is **retired from the power-source path** … Do not reintroduce any
> second power-source acquisition path (SSOT invariant; Atlas design gate). The
> retired method is retained in the codebase as a `NotImplementedError` tripwire …

### §10.6 ShutdownSequencer (supersedes Power-Down Orchestrator)

**BEFORE (the F-1 stale ladder, ~205 lines):**
> ## 10.6 Power-Down Orchestrator (US-216 + US-234)
> Per CIO directive 2 (Spool Session 6), the Pi runs a staged-shutdown ladder …
> [State Machine diagram, VCELL Ladder table, Hysteresis, battery_health_log
> column reuse, Legacy Timer Suppression / TD-D, _powerDownTickLoop, power_log
> Forensic Trail, Stage-Behavior Wiring with WARNING/IMMINENT/AC-restore tables …]

**AFTER (verbatim-equivalent ShutdownSequencer + condensed lesson; ~60 lines):**
> ## 10.6 Shutdown Sequencer (SS-T5, supersedes Power-Down Orchestrator)
> The legacy `PowerDownOrchestrator` staged VCELL ladder
> (NORMAL→WARNING→IMMINENT→TRIGGER) was **deleted** (commit `9adb0fb`, Phase-2 T9)…
> The sole shutdown decider is `ShutdownSequencer` … **Flow.** `PowerSourceProvider`
> reports power LOST → **5 s smoothing** … boot-grace → arm-self-check → bounded
> pre-shutdown **window** of ordered `ShutdownTask`s (V1: exactly one,
> `SyncWithServerTask`; pluggable seam via `__main__.buildV1Tasks`) → graceful
> `systemctl poweroff`. **Emergency:** successful VCELL ≤ `vcellFloorVolts`
> short-circuits to poweroff; failed VCELL read never powers off.
>
> ### Superseded design history (retained for the lesson, not as current behavior)
> **The calibration lesson worth keeping.** … **40-pt SOC% calibration error on this
> MAX17048 unit** — the gauge reads ~60% when VCELL indicates near-empty … VCELL volts
> are the source of truth. This lesson carries over into ShutdownSequencer's
> `vcellFloorVolts` emergency backstop …
> **Why the ladder itself was deleted.** Beyond the calibration finding, the
> ladder *as a shutdown mechanism* was the wrong architecture …

### §11 Wake-on-Power (the F-6 fix)

**BEFORE (the F-6 false `=0 ✅` table):**
> | Value | Behavior on `systemctl poweroff` | Wake-on-power |
> |-------|----------------------------------|----------------|
> | `0` (or absent — default) | SoC halts; PMIC stays awake watching power rails | **Auto-boots when wall power returns** ✅ |
> | Non-zero (e.g. `1`) | Deep sleep; PMIC also stops | **Requires button press or full power-cycle** ❌ |

**AFTER (verbatim-equivalent to corrections-definitive §11; honest empirical-gated):**
> ### Wake-on-Power — Pi 5 + X1209-HAT topology (SS-T9, F-6 closed)
> `POWER_OFF_ON_HALT=1` is the **locked setting** for this system (CIO decision
> 2026-05-18) … **Rationale (topology-specific).** With the X1209 UPS HAT
> holding the Pi's 5 V rail up off its battery, `=0` leaves the PMIC active
> after `poweroff` and the PMIC **never sees a power-cycle edge** … (this is
> Finding B, observed empirically). `=1` powers the PMIC fully off so a USB-C
> power-return is a real boot event.
>
> **The previously documented "`=0` ⇒ auto-boots ✅ / `=1` ⇒ needs button ❌"
> table was FALSE for this topology** … It has been removed, not patched.
>
> **Empirically gated (stated honestly, do not assert beyond evidence).** The
> exact wake mechanism at `=1` … is confirmed by the **Atlas-gated Bench
> Check B (2026-05-18)** at **1 cycle**, and the full **IRL acceptance gate**
> is 5 consecutive clean unattended shutdown→restore cycles … no spec text
> or vendor doc overrides it.

### hardware-reference.md (F-3 + F-4)

**BEFORE (F-3 fictitious table row + example code):**
> | 0x08 | Power Source | 8-bit | enum | 0 = external, 1 = battery |
> …
> # Read power source (0=external, 1=battery)
> power_source = bus.read_byte_data(UPS_ADDRESS, 0x08)

**AFTER (F-3 closed):**
> The MAX17048 fuel gauge on the X1209 exposes battery-health telemetry via
> I2C. **There is no I2C power-source register on this chip** (F-3, SS-T9:
> the table previously listed a fictitious `0x08 Power Source` register; it
> does not exist on the MAX17048 and never did). The power-source fact is
> read from BCM **GPIO 6 PLD** via `PowerSourceProvider` (SSOT), not I2C.
> [corrected MAX17048-only table: VCELL 0x02-0x03 / SOC 0x04-0x05 / CRATE 0x16-0x17]

**HAT identity (F-4 closed):**
> **Identity (SS-T9, F-4 closed).** Geekworm X1209-class board, **vendor-
> confirmed via Geekworm's X1209 wiki + Suptronics' official `pld.py`**, and
> **empirically confirmed on this physical unit by Atlas-gated Bench Check A
> (2026-05-18, PASS)**. The board exposes AC-loss / power-adapter-failure
> detection on **BCM GPIO 6 (digital, HIGH = power present)** …

## Pre-registered gate criteria — evidence
| Criterion | Result |
|---|---|
| **#1 BEFORE/AFTER excerpts** | Provided above for §2, §10.6, §11, hardware-reference.md F-3 + F-4 |
| **#2 Verbatim-equivalent to corrections-definitive.md** | §2 substance lifted verbatim (Markdown style adjusted from `>` blockquote to spec's prose style); §10.6 ShutdownSequencer text verbatim + condensed superseded-history note retaining the calibration lesson explicitly; §11 substance lifted verbatim + Check-B 1-cycle / 5-cycle IRL language preserved |
| **#3 F-3 + F-4 in hardware-reference.md** | F-3: fictitious `0x08 Power Source` register deleted from table + code example. F-4: HAT identity stated "Geekworm X1209, vendor-confirmed + Bench-Check-A PASS" (resolved, not "UNVERIFIED") |
| **#4 Empirical-gated honesty preserved** | §11 says "locked" (CIO decision) / "1-cycle confirmed" (Check B) / "5-cycle IRL still pending" / "drill is sole arbiter". No new false `=1 ✅` certainty |
| **#5 Mod-history + Last Updated** | `specs/architecture.md` Last Updated → 2026-05-19 SS-T9; `docs/hardware-reference.md` mod-history row added |
| **#6 Scope fence** | git diff --stat shows exactly 2 files (specs/architecture.md + docs/hardware-reference.md). **Zero code edits.** README NOT touched (F-5 separate follow-up). |
| **#7 Atlas reviews against corrections-definitive** | This gate request is the review hook |

## `git show --stat`
```
 docs/hardware-reference.md |  72 +++++----
 specs/architecture.md      | 418 +++++++++++++++++-----------------------------
 2 files changed, 178 insertions(+), 312 deletions(-)
```

## Gate request
Per the per-task discipline I **STOP here** and await your gate (the Rule-10
sign-off Marcus is administering as sprint DoD) before Task 10 (the IRL
acceptance runsheet). — Ralph
