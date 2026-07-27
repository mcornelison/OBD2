# I — `specs/UI/tokens.css` STOP-repoint note is stale now that US-484-b landed

- **Filed by:** Ralph (Rex), Sprint 62 (V0.29.16), on completing US-484-b.
- **Owner:** Atlas (tokens.css is the Atlas-gated visual SSOT — `specs/` is
  read-only for Ralph, so this is a request, not an edit).
- **Severity:** low (doc accuracy only; no code or render impact).

## What

`specs/UI/tokens.css:87-94` carries a `RESOLVED 2026-07-26` note that ends:

> The DTC viewer's STOP tier + ribbon MUST be repointed off the BRAND reds
> (`--red` / `--red-light`) onto `--critical-red` — that repoint + Spool's
> multi-channel STOP treatment ships in **US-484-b (V0.29.16)**. Until US-484-b
> lands, any surface still painting STOP with a brand red is the KNOWN-open
> half, not the SSOT intent.

US-484-b has now landed (this sprint). The shipped dashboard renders every
enumerated STOP surface on `--critical-red`, on a near-black field, with the
area/motion/text/full-brightness channels from Spool §6d. The note's forward-
looking framing now reads as an open item that a future audit will try to
re-close.

## Requested change

Reword the block to past tense — e.g. "the STOP repoint + Spool's multi-channel
treatment shipped in US-484-b (V0.29.16); guard:
`tests/ui/test_dashboard_stop_tier_safety.py`" — and drop the "until US-484-b
lands" caveat.

Worth Atlas's judgment while in there: the brand reds are declared **RESERVED,
brand mark ONLY** (`tokens.css:50-57`), but ten non-STOP alarm surfaces in
`dashboard.css` still paint with `--red-light` (down glyph, degraded tiles,
battery-failsafe TRIGGER, LTFT down bars, the DTC detail directive, the
code-re-set result, and the Mode-04 hard-confirm). Those were outside US-484-b's
acceptance and are filed as **TD-067** — they need a Spool severity call plus a
possible Rule-10 token before they can move.

## Grounding

- `specs/UI/tokens.css:59-69` (the `--critical-red` contract) and `:87-94` (the
  stale note).
- `specs/UI/dist/dashboard-pi/dashboard.css` — the shipped repoint.
- `offices/pm/tech_debt/TD-067-brand-red-still-on-non-stop-alarm-surfaces.md`.
