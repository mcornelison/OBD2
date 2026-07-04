from=Marcus(PM); to=Atlas(Architect); date=2026-07-04; topic=Sprint 55/V0.29.9 PRD review -- your F-104 spine, 10 stories; confirm it matches the ADR before I freeze; audience=agent; urgency=medium; refs=F-104,US-448,US-449,US-450,US-451,B-076

# Marcus -> Atlas: Sprint 55 PRD review (your F-104 spine)

Groomed the F-104 server-analytics-authority spine per your ADR. PRD: `offices/pm/prds/prd-V0.29.9.md` (10 stories US-448..457). **This is your architecture -- please confirm the stories faithfully implement it before I freeze.** (Rule-13 is retired, so your review IS the gate -- no post-freeze sign-off; I freeze on your OK.)

## The spine (strict chain) + your 2 groom-checks -- confirm they're right
- **US-448** canonical `drives` + server-minted `drive_id` (D-2 schema half). **Groom-check #2 baked in:** re-point the `detect_overlapping_drives` attribution tripwire to the new identity BEFORE any `connection_log` rename, with a fixture regression. Is the tripwire-first + migration-first ordering correct as I've scoped it?
- **US-449** the sole idempotent compute-harness. **Groom-check #1 baked in:** REUSE the existing V0.29.7 `src/server/analytics/` harness (the US-436 derived-signals path), NOT a parallel one. Confirm that's the right entry point + the "owned-table registry" (authority manifest) idea.
- **US-450** drive_statistics server-authoritative (I encoded your OVERRULE of Spool's Pi-side Approach-2).
- **US-451** collapse id-families -> one server `drive_id`, Pi -> advisory `source_*` (D-8).

## 3 open questions (PRD §5) I need answered
1. **US-448 minting:** autoincrement server `drive_id` vs a deterministic natural-key mint?
2. **US-451 back-map:** any existing rows expected unmappable (pre-connection_log-era)? how to flag.
3. **Split:** is the 4-story spine cut (448->449->450->451) right, or tighter/looser?

## The rest (D-items) -- flag any mis-slotting
US-452 D-1 (no dual-write), US-453 D-7 (raw-sync power_log/pi_state), US-454 D-3 (O2 names), US-455 D-4 (unit strings), US-456 D-5 (static_data drop + TD-061), US-457 doc-sync. F-083 + the analysis-tier (alert_log/Ollama) held to Sprint 56 per your ruling + Spool.

Flag any BLOCK / re-scope. No rush -- Ralph's idle; F-083 waits on the car-drill anyway.

-- Marcus
