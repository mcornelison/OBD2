# BL-027: US-510 A-3 — the brand display face's inlined woff2 asset does not exist

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-510 acceptance A-3 (the `@font-face` half only — A-1 copy + A-2 tokenization SHIPPED) |
| Waiting On   | Iris (supplies the woff2 base64) + CIO (confirms the face) |
| Created      | 2026-07-31                |

## Description

US-510's A-3 acceptance reads:

> add ONE `--font-display` face (**inlined `@font-face` woff2 data-URI**, CSP-safe
> — NO font CDN) for the wordmark + card titles ONLY … **Exact face is a CIO pick
> (Iris supplies the woff2 base64)**

The criterion names its own external dependency, and that dependency has not
been delivered. Verified rather than assumed:

- **No font asset exists anywhere in the repo.** A repo-wide search for
  `*.woff|*.woff2|*.ttf|*.otf` returns exactly one file — `specs/samples/Race
  Sport.ttf` — which is unrelated sample data, not a UI asset.
- **No `@font-face` rule exists** in any shipped surface (`specs/UI/**`).
- **Marcus already tracks it as outstanding.** His groom note to Iris
  (`offices/uidevloper/inbox/2026-07-31-from-marcus-f124-groomed-into-v0.29.23.md`)
  says: *"When you have the woff2 base64 for `--font-display`, drop it and I'll
  make sure US-510 picks it up."*
- **The locked face is Bahnschrift** (Iris's proposal header, CIO-locked
  2026-07-31). Bahnschrift is a Microsoft-bundled proprietary font: it is **not
  redistributable**, and it is **not present on Raspberry Pi OS**. So it cannot
  simply be copied in, and naming it without embedding it does not put it on the
  panel.

I did not fabricate a substitute. Generating font binary/base64 is not something
I can do honestly, and picking a different face is explicitly a CIO decision in
Iris's design lane — inventing one would be the same class of error as guessing
a token hex, which the US-484 line of work spent two stories undoing.

## Impact

**Narrow — one half of one acceptance line.** Everything else in US-510 shipped
and is green:

- **A-1 (copy) — COMPLETE.** Wordmark `ECLIPSE` → `ECLIPSE OBD-II`; parked idle
  footer → `swipe for details · hold or ⋮ for setup`, both restored verbatim
  from the locked idle spec and now pinned by equality.
- **A-2 (tokenization, TD-065/TD-067) — COMPLETE**, including both Atlas Rule-10
  rulings (`--bg`/`--surface` promoted at their shipped values; `--destructive` +
  `--destructive-border` defined and applied, distinct from `--critical-red`).
- **A-3 — the STRUCTURAL half shipped**: `--font-display` is declared in the SSOT
  alongside `--font-mono`, mirrored in `dashboard.css`, and bound to exactly the
  two brand moments (`.idle-wordmark`, `.card-title`). The value is Iris's own
  locked stack, lifted verbatim from her CIO-approved mockup
  (`proposals/2026-07-31-pi-ui-round2-f124.html:16`).

**What is actually missing on the panel:** with no embedded face, the brand
moments resolve down the fallback stack. None of Bahnschrift / DIN Condensed /
Oswald / Arial Narrow ships with Raspberry Pi OS, so the Pi will land on
`system-ui`/`sans-serif` — most likely DejaVu Sans. That IS a visible change (the
wordmark and card titles stop being monospace), but it is **not the CIO-picked
brand face**, and the CIO's original complaint was that the UI "feels generic".
Claiming A-3 as met would be exactly the kind of confident-but-wrong report this
project's honest-instrument rule exists to prevent — hence `passes: false` on
US-510 rather than a quiet pass.

## Attempted Solutions

1. **Searched for a supplied asset** (repo-wide, by extension and by
   `@font-face`/`Bahnschrift` grep) — none.
2. **Checked whether the gate had already been discharged elsewhere** — Atlas's
   2026-07-31 design-gate PASS rules on the *token values* (RULING 2) and says
   nothing about the font asset; it was never his gate to give.
3. **Considered shipping the stack alone as "done"** — rejected: on the target
   panel it renders a generic sans, so the acceptance line would be reported met
   while the CIO's actual complaint stands.
4. **Considered picking a substitute open-licence condensed grotesque** (e.g.
   Oswald, SIL OFL) — rejected: the face is explicitly a CIO pick in Iris's lane,
   and I cannot produce a woff2 binary regardless.

## Proposed Resolution

**Fast-follow, ~30 minutes of work once the asset lands.** The seam is already
built, so this is a payload drop, not a re-design:

1. Iris (or the CIO) drops the base64 woff2 — subset to the glyphs the brand
   moments actually use (uppercase + digits + `-`) to keep it small.
2. Add ONE `@font-face` block to `specs/UI/tokens.css` with
   `src: url(data:font/woff2;base64,…) format("woff2")` and
   `font-display: swap`, then put its family name at the FRONT of the existing
   `--font-display` stack. Nothing else changes: the bindings, the mirror and
   the tests are already in place.
3. Add a test asserting the `@font-face` src is a `data:` URI (never `http`),
   alongside the existing no-CDN pin.

**PM decision needed:** whether US-510 closes as-is with A-3 carried to the
fast-follow (the story's own `conditionalOutcomes` already prefers shipping the
ungated fidelity over blocking the whole story), or stays open until the asset
arrives. Either way the shipped work is committed and green.

## Resolution

[Open]
