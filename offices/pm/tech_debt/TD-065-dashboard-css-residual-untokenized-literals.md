# TD-065 — dashboard.css residual untokenized colour literals (post-US-484-a)

- **Filed by:** Ralph (Rex), Sprint 62 (V0.29.16), during US-484-a.
- **Severity:** low (no visual defect today; it is SSOT-coverage drift risk).
- **Type:** tech-debt / design-SSOT coverage.

## What

US-484-a reconciled the two tokens Atlas has gated (`--green-ok`,
`--text-primary`) and US-484-b owns the STOP/`--critical-red` tier. That leaves a
residue of colour literals in `specs/UI/dist/dashboard-pi/dashboard.css` that are
still outside the SSOT (`specs/UI/tokens.css`). They fall in two groups:

**(a) A literal that DUPLICATES an existing SSOT token — safe to reconcile now.**

- `#2a2f37` at `.dtc-chip[data-level="na"]` and `.dtc-chip[data-level="unknown"]`
  is byte-identical to SSOT `--neutral-chip-bg: #2a2f37` (tokens.css:47), but is
  hardcoded rather than referenced. Pure mechanical fix, no design ruling needed.

**(b) Literals with NO SSOT counterpart — need a token decision first.**

- `--bg: #000000` / `--surface: #111111` — the base background + chrome surface.
  tokens.css explicitly records "base background color … not yet a named token"
  as an intentional gap.
- Takeover gradient edges: `#12603a`/`#062617` (MINOR), `#7a5b00` (WATCH edge).
  These are darker companions to `--green-ok`/`--amber-warn`, not new hues.
- Alpha tints of existing tokens: `rgba(255,196,0,0.06)` (ladder backdrop),
  `rgba(53,196,106,0.18)` (trust badge — updated to the SSOT green in US-484-a).

## Why it's out of US-484-a scope

US-484-a's acceptance is explicitly the two gated tokens, and its AC-4 fences the
slice as "mechanical + safe". Group (b) requires **adding** tokens to the SSOT,
which tokens.css forbids without an Atlas Rule-10 gate (and Spool for any
tuning/severity semantics) — the exact gate that produced BL-024. Inventing a
`--bg`/`--surface`/gradient-edge token inside this story would repeat the drift
the story exists to remove.

Note group (b) is largely *derived* values (alpha/darkened companions of tokens
that already exist), so the design question is not "what hue" but "does the SSOT
tokenize derived shades at all, or only base hues". That is a genuine SSOT-shape
call for Atlas/Iris, not a Ralph call.

## Suggested fix (future story)

1. Cheap half now: repoint the two `#2a2f37` chips onto `var(--neutral-chip-bg)`
   (group (a)) — no gate required, and `tests/ui/test_dashboard_token_ssot.py`
   is the ready-made home for the guard assertion.
2. Route group (b) to Atlas: decide whether the SSOT names base bg/surface and
   derived shades. If yes, add them under Rule-10 and repoint; if no, record the
   "derived shades stay inline" decision in tokens.css so future audits stop
   re-raising it.

## Grounding

- `specs/UI/tokens.css:47` — `--neutral-chip-bg: #2a2f37` (the token that already
  exists for group (a)).
- `specs/UI/tokens.css:81-85` — the explicit "not yet tokenized … base background
  color" gap.
- `specs/UI/dist/dashboard-pi/dashboard.css` — `:root` (`--bg`, `--surface`),
  `#dtc-takeover[data-severity=...]` gradients, `.ladder`, `.dtc-chip[data-level="na"|"unknown"]`.
- `tests/ui/test_dashboard_token_ssot.py` — the US-484-a drift guard these would
  extend.
