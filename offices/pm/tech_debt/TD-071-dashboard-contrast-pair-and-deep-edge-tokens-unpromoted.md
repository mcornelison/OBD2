# TD-071: dashboard `#fff`/`#000` contrast pairs untokenized + three `--*-deep` edge tokens not in the SSOT

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code / design-system      |
| Affected     | `specs/UI/dist/dashboard-pi/dashboard.css`, `specs/UI/tokens.css` |
| Introduced   | US-510 (V0.29.23) — the fidelity pass swept every literal Iris enumerated; these two classes were deliberately left, each for a reason that is not "ran out of time" |
| Created      | 2026-07-31                |

## Description

US-510's acceptance was *"no raw color hex in `dashboard.css` outside `:root`
token defs (for the ungated literals)"*. Every literal Iris enumerated in A-2 is
gone. Two classes remain, both enumerated and pinned so neither can grow:

**1. `#fff` / `#000` contrast pairs (outside `:root`).** ~12 declarations on the
DTC ribbon, the severity chips and the takeover — e.g.
`#dtc-ribbon[data-level="watch"] { background: var(--amber-warn); color: #000; }`.
These are not palette entries. They are the **text colour chosen against that
tier's fill** to clear the WCAG-AA contrast floor; the black on an amber chip and
the white on the critical-red band are answers to a *contrast* question, not
instances of a shared colour. Naming them properly means adding
`--on-amber` / `--on-critical` / `--on-green` style tokens.

`tests/ui/test_dashboard_fidelity_pass.py::test_theOnlyRawHexLeftOutsideRoot_isTheBlackWhiteContrastPair`
allows **exactly** `#fff` and `#000` in short form and nothing else, so a new
colour literal fails immediately, and the long-form `#000000` is separately
forbidden outside `:root` (that value is `--bg`'s job now).

**2. `--amber-deep` / `--green-deep` / `--green-deepest` live only in
`dashboard.css`.** US-510 relocated the DTC takeover's deep gradient edges
(`#7a5b00`, `#12603a`, `#062617`) out of the surface rules and behind names, but
declared them in the dist `:root` rather than in `specs/UI/tokens.css`. That
makes them the only tokens on this surface without an SSOT counterpart — a mild
fork of the two-file mirror discipline.

## Why It Was Accepted

**Both are somebody else's call, not a shortcut.**

- A **new SSOT token name** is an Atlas Rule-10 addition, and his 2026-07-31
  ruling covered exactly `--bg`, `--surface`, `--destructive` and
  `--destructive-border`. `--amber-deep` et al. were not ruled, so promoting them
  inside US-510 would have been an un-gated SSOT edit.
- **What the contrast pairs should be called is a design decision** in Iris's
  lane (is it `--on-amber`, or a general `--text-on-fill`? does the STOP band's
  white differ from the chip's?). Inventing a vocabulary for her is the same
  class of error as guessing a hex value.
- Getting them out of the surface rules and behind *a* name was the part US-510
  could do without guessing, and it is done — a raw literal buried mid-rule is
  strictly worse than a named one in `:root`, even an unpromoted one.

Also worth recording: the deep-edge tokens hold the **exact pre-existing
literals**. Iris offered a derived `color-mix()` as an alternative; that was
declined deliberately because a computed mix yields a *different* colour, and
US-510's governing rule (Atlas) was that a diff moving rendered pixels FAILS.

## Risk If Not Addressed

**Low, and bounded by tests.** Neither class can silently spread: the whole-file
guard rejects any new hex outside the allow-set, and the token-SSOT tests reject
any value drift in the mirrored tokens. The residual risks are:

- **Cosmetic/consistency:** a reader of `tokens.css` sees an incomplete picture
  of the palette (three colours the dashboard uses are not there).
- **Real but unlikely:** if a future surface (a second takeover, a tuning gauge)
  wants the same deep-amber edge, it has no SSOT token to reference and will
  either re-fork the literal or import from the dist — the exact drift the SSOT
  exists to prevent. This becomes likely only when a *second* consumer appears.
- The contrast pairs are genuinely correct as written today; the debt is naming,
  not behaviour. No panel renders differently because of this.

## Remediation Plan

Two independent, small pieces — neither blocks the other:

1. **Promote the deep edges (Atlas, Rule-10).** Route `--amber-deep #7a5b00`,
   `--green-deep #12603a`, `--green-deepest #062617` for a token-addition nod,
   then move the declarations into `specs/UI/tokens.css` and keep the dist as a
   mirror. Pure consolidation, zero visual change; add them to the value-equality
   loop in `tests/ui/test_dashboard_token_ssot.py`.
2. **Name the contrast pairs (Iris, then Atlas).** Ask Iris for the vocabulary
   (`--on-amber` / `--on-critical` / …), gate the names, then repoint the ~12
   declarations and tighten
   `_ALLOWED_CONTRAST_HEX` in `tests/ui/test_dashboard_fidelity_pass.py` to the
   empty set — at which point the acceptance line becomes literally true with no
   exception, and the test guarding it needs no allow-list at all.

Best bundled into the next UI-polish sprint alongside BL-027's `@font-face`
fast-follow, since all three touch the same two files.
