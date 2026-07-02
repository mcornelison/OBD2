# Atlas Rulings — BL-014 (power-mode SSOT) + BL-015 (SoC% recording path/schema/cold-start)

**By:** Atlas (Architect) · **Date:** 2026-07-01 · **Requested by:** Marcus (`2026-07-01-from-marcus-bl014-bl015-sprint51-architecture-rulings`) · **CIO-ratified 2026-07-01**
**Scope:** US-421 (F-098), US-422/423 (F-060/F-061), carried to Sprint 52. Ralph refused-first correctly — the groom premises were invalidated by since-landed code. A-4/SSOT lane. Verified against the code.

## Verified (premises hold)
- `power_source_provider.py` = `isExternalPowerPresent()`/`isPowerLost()` — external-AC vs UPS-battery, NOT in-car-vs-wall deployment mode. No existing `pi.power.mode` / `powerMode` source.
- `PowerDownOrchestrator` = deleted (comments only, `boot_reason.py`); `hardware_manager` `batteryHealthRecorder` = a wired-but-dead param (ghost of the deleted path); `scripts/record_drain_test.py` = the live "monthly drain-test drill" recorder.
- `battery_health_log` = `start_soc`/`end_soc` (hold VOLTS, redundant with `*_vcell_v`; US-423 drops them) + NO `soc_pct` column, both tiers (`models.py:738-739`).

## BL-014 — power-mode SSOT (US-421, F-098) — RULING
**Static config-key SSOT, CIO-ratified.** A single new `PowerModeProvider` in `src/pi/power/` reads a config key **`pi.power.mode` ∈ {car, wall, unknown}, default `unknown`**, and feeds the badge's `powerMode`. Undeterminable/stale → **`unknown`**, never a confident-wrong mode.
- **NOT a runtime auto-detector.** There is no reliable software signal (external-AC ≠ deployment mode; an OBD-connection proxy is confounded — engine-off/OBD-unplugged in-car reads as "wall" → dishonest instrument). Static + explicit is the honest choice; the operator sets it on bench↔car deploy (config edit + restart).
- **Ralph's candidate is correct** — zero existing acquisition paths, so one provider introduces no SSOT second-path violation.
- **Future (CIO, low priority):** a hardware sense line on a GPIO (like the Pi's power-relay pin) = the eventual hard-wired truth. **Design the provider so acquisition is swappable behind the SSOT seam** — when the GPIO lands, `PowerModeProvider` swaps config→GPIO with **zero consumer change** (the whole point of one provider). Not this sprint; wall-power-only dev now, and in normal ops the display is off when the Pi is off.

## BL-015 — SoC% recording (US-422 F-060; US-423 F-061) — RULINGS

**1. Recording path — the bench drain-test CLI (CIO-ratified).** Wire `UpsMonitor` SoC% into `scripts/record_drain_test.py` (its `startDrainEvent`/`endDrainEvent`). **NOT** a ShutdownSequencer drain-event — that path is deleted/retired and semantically broken (a drain that opens+closes inside the ~10 s poweroff records runtime≈10 s, not the real battery-backed drain). **Cleanup:** remove the dead `batteryHealthRecorder` reference in `hardware_manager` (ghost of `PowerDownOrchestrator`) — file as tech-debt so it doesn't re-confuse a future groom.

**2. Schema — add `*_soc_pct`, both tiers, coordinated with US-423's drop.** Add `start_soc_pct` / `end_soc_pct` (`REAL`/`Float`, nullable) on BOTH tiers (Pi SQLite rebuild-migration + server `models.py` + sync mapping), sourced from the **MAX17048 SoC register only** (never the misnamed voltage columns). **A-4:** identical both tiers, one definition. **Split (Marcus flagged — YES):** the legacy `start_soc`/`end_soc` (volts, redundant with `*_vcell_v`) that US-423 drops and the new `*_soc_pct` are the same table on both tiers → do them in **ONE forward-only both-tier migration** (drop legacy `_soc` + add `_soc_pct`), as a **schema story** distinct from the Pi-wiring (US-422). **Ordering note:** this inverts the current dep — the schema migration lands BEFORE the wiring (US-422 can't write `_soc_pct` until it exists). Recommend either (a) one coordinated "battery_health_log SoC% correctness" story (migration + CLI wiring together, tightly coupled), or (b) schema-story → US-422-wiring. Story structure is your call; the architecture is: migration first, both-tier-identical, then wire.

**3. Cold-start guard (US-234) — RULING.** The MAX17048 SoC register is garbage for ~3 min after cold power-up (the reason the ladder moved off SoC onto VCELL). SoC% read within the calibration window → record **NULL / flagged, never a garbage percent** (honest-instrument; consistent with the US-264 SOC-uncalibrated rule). The operator-initiated drill usually runs after warm-up so it's rare, but the guard lives in the recording path regardless (register-not-calibrated → no number).

## Disposition
- All four decisions ruled + CIO-ratified. Marcus re-grooms US-421/422/423 into Sprint 52 to these.
- Split recommended (BL-015): schema (both-tier migration) separate from wiring (US-422); migration ordered first.
- Rule-13 on freeze as usual.

— Atlas
