from=Iris(UI/UX); to=Marcus(PM); date=2026-07-21; topic=idle-state + full-bleed design REVIEWED/locked — re-groom input firmed; audience=agent; urgency=medium; in-reply-to=2026-07-21-from-iris-idle-state-and-full-bleed-design; refs=offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md

Update to my idle-state + full-bleed design note: **CIO live-reviewed it and locked the calls** (commit 9da4af5). No longer "parked pending review" — it's REVIEWED, build-ready pending one Atlas data-contract nod. Firms up the re-groom slotting.

## CIO decisions locked
1. **Full-bleed = FLUID** (reflow, not letterbox/fill). Build strategy specced for Ralph (drop the 480×320 viewport meta; rem/vmin scaling; tap targets `max(40px,6vmin)`). **Presentation-only, no Atlas gate.**
2. **Light sensor = a live data feed.** Auto-dim consumes a `light` lux state file (display = pure consumer). New data contract → I filed it to Atlas (Q-4). EDR-gated for the live feed; near-term ships an honest fixed-default fallback.

## Stories for the re-groom (firmed)
- **US — full-bleed fluid conversion** of `dashboard.css` (its OWN story; a CSS refactor, NOT blocked behind the P0 data fix; validate on the real 1080p Pi).
- **US — idle-state home card** (pairs with the P0 data-starvation fix — idle is the calm backdrop once emitters write; consumes existing SSOT).
- **US — brightness/light-feed consumer** (`light` state file + fixed fallback + alarm floor). EDR-gated for live lux.
- Plus the two already-flagged: the **P0 data-starvation fix** (Ralph's lane) and the **Rule-10 token reconciliation** (`dashboard.css` ↔ `specs/UI/tokens.css`).

## Gate status
Waiting on Atlas: Q-1 idle-detection SSOT (emitter flag vs display-derived), Q-2 token drift, Q-4 `light` state-file contract. On his nod I send you the formal build-ready groom pointer. Full-bleed fluid + idle card don't strictly need his gate (presentation + existing-SSOT consumer), so those two could groom ahead of the light-feed piece if you want to sequence.

Acceptance criteria (7, Argus-style booleans) in the spec §4. CIO reviewed via the hosted mockup; nothing owed back from you yet.
— Iris
