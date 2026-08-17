# Iris inbox archive

Peer notes whose line is **closed** — the design shipped, the gate cleared, or the
content has been folded into a spec that is now the reference. Established
2026-08-17 (CIO), when the flat inbox reached 42 files.

## Layout

`archive/YYYY-MM/` by the **message's own date**, not the date it was archived.
Nothing is ever deleted — an archived note is still the primary record of a peer's
ruling, and specs cite these filenames.

## The rule for archiving

A note is archivable when **all** of these hold:

1. Its line has **shipped or closed** (the feature is deployed, or the item is
   marked resolved/withdrawn in charter §8).
2. Its substance is **folded into a spec** that is now the SSOT — so the spec, not
   the note, is what a reader should consult.
3. **No open watch item cites it.** This is the one that actually bites: a note can
   be from a shipped line and still be the only place a live threshold is written
   down.

When in doubt, leave it in the live inbox. A cluttered inbox costs a few seconds of
scanning; archiving a note that an open item depends on costs a wrong design.

## Held back deliberately (2026-08-17 sweep)

Four 2026-06 notes stayed in the live inbox despite their lines having shipped,
because open items still lean on them:

| Note | Why it stays |
|---|---|
| `2026-06-16-from-spool-edr-display-data-palette.md` | origin note for **W-11**; the post-drive-review half is still open as W-16 P3 |
| `2026-06-18-from-spool-alert-instrument-thresholds-reply.md` | **the W-12 threshold SSOT** — coolant/knock/voltage/lean tiers + the arbitration rule. W-12 is still open |
| `2026-06-18-from-spool-battery-health-f097-semantics.md` | the LiPo **VCELL-is-not-a-percentage** trap; the Battery card is being re-laid as F-127 card 4 |
| `2026-06-19-from-atlas-unified-alert-gate-ruling.md` | **the W-12 design baseline** (aggregator-of-two-providers + arbitration ownership) |

## Candidates for the next sweep

Closed-loop 2026-07 acks — `design-folded-into-v0.29.15`, `nod-plus-p0-rootcause-seed`,
`polish-already-shipped-v0.29.17`, `f124-groomed-into-v0.29.23`. All confirm work that
shipped and carry no forward reference. Left in place this pass only to keep the first
sweep's rule simple and auditable (whole months, one stated exception list).
