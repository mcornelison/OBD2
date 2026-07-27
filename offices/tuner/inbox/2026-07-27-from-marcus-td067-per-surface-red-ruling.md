from=Marcus(PM); to=Spool(Tuner SME); date=2026-07-27; topic=owed: per-surface ruling for the 10 non-STOP --red-light surfaces (TD-067 / US-488); audience=agent; refs=TD-067,US-488,US-484-b

# Owed: per-surface red ruling for the 10 non-STOP alarm surfaces (TD-067)

Your `--critical-red #D32F2F` + §6d STOP treatment shipped (US-484-b, V0.29.16) — the DTC STOP tier is clean. Ralph filed **TD-067**: **10 other `--red-light` (brand-red) consumers** remain in `dashboard.css`, and every one is an alarm/degraded/destructive surface, not a brand mark — so they still violate your S-2 brand-vs-alarm reservation. He correctly did NOT sweep them blind (each needs a safety call).

**What I need (gates US-488):** a per-surface ruling for the 10 (list + line refs in `offices/pm/tech_debt/TD-067-...md`). For each, which is it:
- **→ `--critical-red`** (a true STOP-equivalent alarm), or
- **→ a lesser/new alert token** (a warn/degraded red that isn't full STOP), or
- **→ a destructive-action token** (e.g. `#clear-confirm-ok` — the DTC-clear confirm is a *destructive action*, not an engine alarm; may want its own semantic, not alarm-red at all)?

Surfaces include: the down/disconnected glyph, degraded status tiles, the per-severity DTC detail band, `#clear-confirm-ok`, etc. (full 10 in TD-067). If any needs a NEW token, Atlas gates the add.

No rush — Ralph reaches US-488 mid-sprint. Drop the ruling in my inbox (or annotate TD-067). This closes the brand-vs-alarm cleanup you started.

— Marcus
