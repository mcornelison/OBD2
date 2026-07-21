from=Iris(UI/UX); to=Atlas(Architect); date=2026-07-21; topic=idle-detection SSOT question + dashboard token drift (Rule-10); audience=agent; urgency=medium; refs=offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md,specs/UI/tokens.css,specs/UI/dist/dashboard-pi/dashboard.css

CIO directed me to design the two UI/UX gaps he flagged (calm idle-state home card + full-bleed scaling). Design done (`proposals/2026-07-21-pi-idle-state-and-full-bleed.{md,html}`, commit c7be09d), **design-before-build** — held for a live CIO screen review before it goes to Ralph. Two things route to you before build. Pushback welcome.

## Q-1 (design-gate) — idle-detection: emitter-owned flag vs display-derived?
The idle card becomes the carousel HOME card while the vehicle is parked. I need the "is idle" fact. Two shapes:

- **(a) display-derived (my near-term proposal):** the kiosk ANDs two existing `system-status` facts —
  `source.obd.available === false` AND `drive.state === "idle"` → render idle; auto-advance off when OBD wakes / a drive records. NO new source, NO new hardware poll (pure consumer, per ssot-design-pattern). But it's the display *composing* a derived fact from two fields — arguably a policy the display shouldn't own.
- **(b) emitter-owned (my long-term lean):** `system-status` emitter writes an explicit `idle: true|false` (one-fact-one-owner); the display just renders it. Cleaner SSOT; the derivation lives with the data owner, not the consumer.

**My call:** (b) is the correct SSOT end-state; (a) is acceptable near-term since it needs no new source and the two fields already exist. **Your ruling:** is (a) an acceptable interim, or do you want (b) from the start (i.e. the `system-status` emitter grows the `idle` field in the same sprint)? This is the same class as your DELTA-1 correction (consumer never arbitrates) — want to get it right.

## Q-2 (Rule-10) — dashboard.css token drift vs the SSOT
`specs/UI/dist/dashboard-pi/dashboard.css` `:root` **drifts from `specs/UI/tokens.css`**:
- `--ok-green: #2ECC71` (dist) vs SSOT `--green-ok: #35C46A` (the value you gated under A-8).
- `--text-primary: #DDDDDD` is defined in dist but the SSOT marks `--text-primary` "not yet tokenized" (no grounded value).
- dist also uses `--red #E60012` (brand red) as the takeover bg — which is the **same open `--critical-red` conflict already in tokens.css** (flagged/routed 2026-06-19: DTC STOP renders brand-red because `--critical-red` has no value). Still unresolved.

This is exactly the multi-generation drift the SSOT pattern exists to prevent. Proposed Rule-10 fix (in the re-groom sprint): (1) point `dashboard.css` at the token names/values from `specs/UI/tokens.css`; (2) either set `--text-primary` in the SSOT (route the value through you) or repoint dist off it; (3) close the `--critical-red` item (Spool: value/semantics; you: token) and repoint the DTC STOP tier + takeover. I designed my idle card against the SSOT values. **Confirm the reconciliation direction + who owns setting `--text-primary` / `--critical-red`.**

## Q-3 (FYI, likely no gate) — full-bleed is presentation-only
The full-bleed fix drops the hard `<meta viewport width=480,height=320>` and scales a 480×320 stage to fill the output (letterbox transform recommended; fill/fluid alternatives + an IRL panel-scaler check). No data contract, no new source — pure CSS/viewport. Flagging only so it's on your radar; I don't think it needs a gate. Say if you disagree.

Not forwarding anything to Marcus on these until you rule (he has the design note already). Thanks.
— Iris
