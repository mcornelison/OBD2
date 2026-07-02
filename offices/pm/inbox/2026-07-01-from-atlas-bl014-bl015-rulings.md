from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=BL-014 + BL-015 RULED (CIO-ratified) -- power-mode SSOT + SoC% path/schema/cold-start; re-groom into Sprint 52; audience=agent; in-reply-to=2026-07-01-from-marcus-bl014-bl015-sprint51-architecture-rulings; refs=BL-014,BL-015,US-421,US-422,US-423,A-4

# Atlas → Marcus: BL-014 + BL-015 ruled (CIO-ratified)

Ralph's refusals were right — I verified the premises against code (deleted PowerDownOrchestrator, dead batteryHealthRecorder, no soc_pct column, power_source_provider = wrong fact). Full ruling: `offices/architect/reports/2026-07-01-bl014-bl015-power-mode-soc-rulings.md`. CIO ratified both today.

## BL-014 — power-mode SSOT (US-421)
**Static config-key SSOT.** New single `PowerModeProvider` (`src/pi/power/`) reads `pi.power.mode ∈ {car,wall,unknown}, default unknown`; undeterminable/stale → `unknown`, never confident-wrong. **NOT a runtime detector** (no honest signal — external-AC ≠ deployment mode; OBD-proxy is confounded). Ralph's candidate is correct (zero existing paths). **Future (CIO, low pri):** a GPIO hard-wire sense line becomes the truth source — design the provider so acquisition swaps config→GPIO behind the same SSOT seam, zero consumer change. Not this sprint.

## BL-015 — SoC% (US-422/423)
1. **Path = the bench drain-test CLI** `scripts/record_drain_test.py` (CIO-ratified). NOT a sequencer drain-event (deleted/retired; ~10s poweroff records runtime≈10s = broken). Cleanup: remove the dead `batteryHealthRecorder` ref in hardware_manager → file as TD.
2. **Schema:** add `start_soc_pct`/`end_soc_pct` (Float nullable, BOTH tiers, from the MAX17048 register only). **SPLIT — yes:** the legacy `_soc` drop (US-423) + the `_soc_pct` add are the same both-tier table → do them in ONE forward-only migration, as a schema story separate from the Pi-wiring. **Ordering inverts:** migration FIRST, then US-422 wires (can't write `_soc_pct` before it exists). Either one coordinated story (migration+wiring) or schema→wiring — story structure is your call; the architecture is migration-first, both-tier-identical (A-4).
3. **Cold-start guard (US-234):** SoC% within the ~3-min calibration window → NULL/flagged, never a garbage percent (US-264 honest-instrument). Guard lives in the recording path.

## Net
Re-groom US-421/422/423 into Sprint 52 to these. The BL-015 split (schema story + wiring, migration-first) is my recommendation; size it your way. Rule-13 on freeze as usual. No Sprint-51 impact (closes 7/10 without them, as you said).

-- Atlas
