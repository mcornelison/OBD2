# Vehicle Knowledge Index — 1998 Mitsubishi Eclipse GST

**Quick-reference index into the atomic vehicle cards in `cards/`.**

> This file is an **index, not a source of truth.** Authoritative facts about THIS specific car live in `cards/*.md` (one fact per card, SSOT). This index is intended to be **generated from card front-matter** (`id` / `title` / `ecu` / `status` / `summary`); it is hand-seeded today and will become a build artifact once the card migration completes.
>
> - **THIS-car facts** → `cards/` (indexed here).
> - **General 4G63 / DSM / tuning craft** (PID interpretation, knock theory, fuel-trim trees, failure modes, glossary, ECMLink capability reference) → stays in `knowledge.md`.
> - Card schema + conventions → `cards/README.md`.

## Live cards

| Card | ECU | Status | Summary |
|------|-----|--------|---------|
| [[ecu-prior-md346675]] | prior | current | 1998 factory FWD-turbo ECU; 100% stock, never flashed; flash-hardware but not ECMLink-flashable; drives ≤24 = stock baselines. |
| [[ecu-new-md335287]] | new | current | 1997 ECMLink-V3 board, installed 2026-05-22; running prior-tuner ECMLink tune; Mode 09/22 silent; SPEED reads ~2× actual. |

## Planned cards (migration manifest)

The full set to extract from `knowledge.md` during the MrSpool RAG sprint. Each becomes one atomic card with front-matter. **ECU group seeded ✅; rest PLANNED.**

**ECU** — `ecu-prior-md346675` ✅ · `ecu-new-md335287` ✅ · `ecu-swap-2026-05-22` (event + install/removal timestamps + reason)

**Vehicle identity & mods** — `vehicle-identity` (VIN, 76k mi, 7-bolt, manual) · `mods-installed` · `parts-in-hand` · `parts-to-order` · `summer-2026-install-plan` · `illinois-emissions`

**OBD capability (this car)** — `obd-supported-pids` (16 confirmed) · `obd-unsupported-pids` (0x0A/0x0B/0x42 + workarounds) · `battery-voltage-via-elm` (ATRV)

**Safe ranges (this car, by mod level)** — `safe-range-coolant-temp` · `safe-range-timing-knock` · `safe-range-afr` · `safe-range-boost` · `safe-range-battery-voltage`

**Empirical drives** — `drive-005-cold-warm-baseline` · `drive-006-cold-start-city` · `drive-007-under-load-baseline` · `drive-011-knock-retard` *(archived-historical, prior ECU)* · `drive-026-newecu-first-knock` *(current, new-ECU working baseline)* · `session-023-first-light` *(archived-historical)* · `session-006-thermostat-drill`

**This-car systems** — `cooling-thermostat-behavior` (I-016 closed benign) · `fuel-system-stock-specs`

**Mod path & pre-wire** — `mod-priority-path` · `prewire-wideband-o2` · `prewire-e85-flex-fuel`

## Explicitly NOT carded (not vehicle tuning knowledge)

UPS HAT / drain-test / regression-fixture sections of `knowledge.md` are **infrastructure / dev artifacts**, not Eclipse tuning facts — excluded from the vehicle corpus (pending relocation decision; see `rag-readiness-assessment.md` §7).
