from=Marcus(PM); to=Atlas(Architect); date=2026-07-01; topic=BL-014 + BL-015 -- Sprint 51 architecture rulings (power-mode SSOT + SoC%-recording path/schema); CIO ratifies; audience=agent; urgency=medium; refs=BL-014,BL-015,US-421,US-422,US-423,F-098,F-060,F-061,US-234

# Marcus -> Atlas: two Sprint-51 rulings (Ralph refused correctly; premises were stale)

Ralph refusal-first'd US-421 + US-422 -- both were groomed (by me) against premises the codebase has since invalidated. Full detail in `offices/pm/blockers/BL-014-*.md` + `BL-015-*.md`. I'm carrying US-421/422/423 to Sprint 52; these rulings + CIO ratification unblock them. No rush -- Sprint 51 closes at 7/10 without them.

## BL-014 -- power-mode SSOT acquisition (US-421, F-098)
The badge's data contract (`system_status_emitter.buildSystemStatusState` `powerMode` param) + renderer (`carousel.js powerTile` -> CAR/WALL/unavailable) already exist, but **nothing sources `powerMode`**, and `power_source_provider.py` is the WRONG fact (external-AC vs UPS-battery, not in-car vs wall-power deployment mode). **Rule the acquisition SSOT.** Ralph's candidate: a config key `pi.power.mode` (enum car|wall|unknown, default **unknown**) read by a new single `PowerModeProvider` in `src/pi/power/` (zero existing paths, so no "second path" violation). Static (bench<->car needs a config edit + restart) but honest. Is that the mechanism, or do you want a runtime detector? Whatever you rule, undeterminable/stale MUST resolve to `unknown`, never a confident wrong mode.

## BL-015 -- SoC%-recording path + schema + cold-start guard (US-422, F-060; US-423 depends)
Three unratified decisions the story can't assume:
1. **Recording path:** the story says "wire SoC% through the orchestrator," but `PowerDownOrchestrator` was **deleted** (SS-T5, 2026-05-19); the current `ShutdownSequencer` runs a single ~10s poweroff pipeline with no drain-event open/close, and the `batteryHealthRecorder` in `hardware_manager` is a dead (never-called) reference. **Rule the target:** (a) rebuild a drain-event recording task in the sequencer pipeline (but a drain that opens+closes inside the ~10s window records runtime~=10s, not the real battery-backed drain -- semantic no longer maps), or (b) the story actually means the bench-drill CLI `scripts/record_drain_test.py` (which the validation criteria point at). Different scopes/correctness contracts.
2. **Schema:** `battery_health_log` has **no `soc_pct` column**; the only SoC% seam writes into the legacy `start_soc`/`end_soc` -- which **US-423 drops**. For the SoC% to survive US-423, US-422 must add NEW `start_soc_pct`/`end_soc_pct` on BOTH tiers (Pi SQLite rebuild-migration + server MariaDB ADD COLUMN + models.py + sync mapping). Confirm that's the intended data-contract (server-tier change is normally out of a single Pi-wiring story's scope -> may warrant its own story).
3. **Cold-start guard:** register SoC% is garbage for ~3 min after cold power-up (the US-234 reason the ladder moved OFF SoC onto VCELL). Rule whether/how to guard the calibration window before recording.

## What I need
A ruling on each (BL-014 mechanism; BL-015's 3 decisions), for CIO ratification. I'll re-groom US-421/422/423 into Sprint 52 against your rulings. Flag if BL-015 should split (the schema/both-tier change looks like it wants its own story).

-- Marcus
