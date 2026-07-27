# TD-067 — brand `--red-light` still paints non-STOP alarm surfaces

- **Filed by:** Ralph (Rex), Sprint 62 (V0.29.16), during US-484-b.
- **Severity:** low-medium (no engine-safety defect — the STOP tier is clean —
  but it keeps the brand-vs-alarm collision alive on 10 other surfaces).
- **Type:** tech-debt / design-SSOT (brand-token reservation).
- **Status: 8 of 10 surfaces SWEPT** by US-488 (Sprint 63, V0.29.17). **OPEN on
  the last 2 only** — the `#clear-confirm` pair, blocked on a `--destructive`
  token that does not exist yet (Iris owns the value, Atlas gates it under
  Rule-10). See "Remaining" below. Do NOT close this TD until those two land.

## Remaining (the whole of the open debt)

| Line | Surface | Blocked on |
|---|---|---|
| ~596 | `#clear-confirm .confirm-box` | `--destructive` value + Atlas Rule-10 gate |
| ~598 | `#clear-confirm-ok` | same |

Spool's ruling (2026-07-27) is why these two could not ride along with the other
eight: a **destructive user action is a different axis** from the engine
severity tiers. It **MUST NOT** be any alarm-red (Mode-04 wiping stored codes is
not an engine emergency, and reusing the pull-over red re-creates exactly the
"one red, two meanings" collision this TD exists to kill) and **MUST NOT** be
amber (that means WATCH). So it needs its own token — and inventing a hex for it
inside US-488 would have re-forked the SSOT that US-484-a/b spent two stories
un-forking.

Both are pinned by `tests/ui/test_dashboard_alarm_tier_sweep.py`: the whole-file
guard asserts these are the **only** two rules in the sheet still touching a
brand red (so the debt cannot grow), and a scope-fence test asserts
`--destructive` is declared/rendered in **neither** file (so it cannot
half-land). Closing this TD = repoint those two + delete the
`_DEFERRED_DESTRUCTIVE` tuple; both guards then tighten to zero automatically.

## What US-488 swept (2026-07-27, per Spool's per-surface ruling)

"Red = danger, one meaning only" — no second alarm-red was invented.

| Surface | Now | Why |
|---|---|---|
| topbar `down` glyph | `--amber-warn` | degraded ≠ dangerous |
| `.tile[data-level=down]` value | `--amber-warn` | same |
| `.ltft-bar[data-level=down]` value + border | `--amber-warn` | ±10% drift is WATCH |
| `#dtc-clear-result[reset]` | `--amber-warn` | hard fault → "get diagnosed" |
| `.ladder[data-stage=TRIGGER]` + banner | `--critical-red` | terminal act-now SYSTEM state; earlier stages stay amber so the escalation still escalates; copy stays "DRAINING · TRIGGER", never "PULL OVER" |
| `.detail-directive` | **tier-driven** | see below |

The `.detail-directive` refactor was the load-bearing one: one blanket brand red
for *every* severity inverted the ramp twice — a WATCH code's directive read
*redder* than the `--critical-red` chip beside it, and a MINOR gas-cap code got
a red instruction it never earned. It is now `data-level`-driven (STOP →
`--critical-red`, WATCH/unknown → `--amber-warn`, MINOR → `--green-ok`, base
neutral), tagged in `carousel.js` from the **same** tier the chip uses so the two
can never disagree.

## Original filing (Sprint 62) — retained for context

## What

`specs/UI/tokens.css:50-57` declares the brand reds **RESERVED — brand mark
ONLY**, on Spool's S-2 grounds: *"if the permanent brand mark is red AND a
critical alarm is also red, the driver cannot tell 'brand' from 'danger'."*

US-484-b repointed the surfaces its acceptance enumerated — the DTC STOP ribbon,
STOP chip, STOP hero border, the STOP takeover, and `#confirm-ok` — onto
`--critical-red`. Ten `var(--red-light)` consumers remain in
`specs/UI/dist/dashboard-pi/dashboard.css`, and **every one of them is an alarm
or degraded state, not a brand mark**:

| Line | Surface | What it signals |
|---|---|---|
| 66 | `#topbar .glyph[data-state="down"]` | a link/service is DOWN |
| 157 | `.tile[data-level="down"] .tile-value` | a degraded status tile |
| 176-177 | `.ladder[data-stage="TRIGGER"]` + banner | the battery failsafe TRIGGER stage |
| 202-203 | `.ltft-bar[data-level="down"]` | a fuel-trim drive beyond ±10% |
| 507 | `.detail-directive` | the DTC detail directive band (all tiers) |
| 569 | `#dtc-clear-result[data-level="reset"]` | a code that RE-SET after a clear (§4d hard fault) |
| 579, 581 | `#clear-confirm .confirm-box`, `#clear-confirm-ok` | the Mode-04 hard-confirm |

Two are worth calling out. **`.detail-directive` (507)** colours the directive
band for *every* severity, so a STOP code's own detail text is still brand red
even though its chip and hero are not — the one place US-484-b's repoint reads
inconsistent. **`#clear-confirm-ok` (581)** is the sibling of the `#confirm-ok`
the story did repoint, and it guards the *more* consequential action (Mode 04
wipes every code + freeze frame), so it is now the weaker-styled of the pair.

## Why it's out of US-484-b scope

The story's AC-2 enumerates its four surfaces plus the takeover, and AC-6 scopes
the grep to "the STOP tier". Sweeping the other ten would have meant deciding,
per surface, whether a `down`/`TRIGGER`/`reset` state is a *pull-over alarm*
(`--critical-red`) or a lesser degraded state that wants its own token — a Spool
severity-semantics call plus an Atlas Rule-10 gate if a new token is needed.
Guessing that inside a safety story is exactly the drift US-484 exists to remove.

## Suggested fix (future story)

1. **Spool** classifies each surface above: pull-over alarm vs. degraded-but-not-
   dangerous. Note the severity taxonomy already has three tiers (§3) but the
   *display* only has one alarm red — that mismatch is the root of this TD.
2. **Atlas** gates any new token (e.g. a `--degraded` / `--down` red distinct
   from both brand and `--critical-red`) into `specs/UI/tokens.css` under Rule-10.
3. **Ralph** repoints + extends `tests/ui/test_dashboard_stop_tier_safety.py`'s
   `test_noStopSurfaceReferencesABrandRed` into a whole-file assertion: **no**
   `var(--red*)` outside a brand-mark rule.
4. Cheap, no-gate half if the CIO wants partial progress now: `.detail-directive`
   (507) and the `#clear-confirm` pair (579/581) are all DTC-alarm surfaces
   already covered by `--critical-red`'s semantics — repointing just those three
   needs no new token and removes the inconsistency US-484-b introduced.

## Grounding

- `specs/UI/tokens.css:50-57` — brand reds RESERVED, brand mark ONLY (Spool S-2).
- `offices/tuner/dtc-display-clear-safety-advisory.md` §6d ch.2 — STOP "never on
  brand chrome"; §3 — the three-tier severity taxonomy.
- `specs/UI/dist/dashboard-pi/dashboard.css` — the 10 lines tabled above.
- `tests/ui/test_dashboard_stop_tier_safety.py::test_noStopSurfaceReferencesABrandRed`
  — the guard that currently covers only STOP-selector rules.
