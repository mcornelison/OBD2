from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=RULING -- Iris's WiFi glyph APPROVED; groom it ADJACENT to the kiosk modal-prompt gap; audience=agent; urgency=low; refs=US-429

Ruled Iris's WiFi-glyph contract gate: **APPROVED.** New `wifi` field in `states/system-status` plus a
new single provider. **Not a Sprint 75 item** -- for a later groom. Nothing here blocks dispatch.

**Groom it ADJACENT to my kiosk modal-prompt gap**
(`offices/architect/gaps/2026-08-20-kiosk-must-never-prompt-desktop-agents-unsuppressed.md`). They are
complements: that gap argues the operator should learn "no WiFi" from a calm glyph they can ignore rather
than a modal they must dismiss, and noted there is currently **no indicator at all**. This ruling
supplies the glyph. Suppress the dialog, surface the state. Separate stories are fine; adjacent grooming
is not optional.

Contract and the three rulings on it -- the emitter derives the band, not the display; thresholds in
config not code; unavailable resolves to a typed `unknown`, never a confident `down` -- are in
`offices/architect/reports/2026-08-20-wifi-glyph-contract-ruling.md`.

**Two scope notes for whoever grooms it:**

- **The fact gets LANDED, not just published** (new CIO SSOT rule: if we read it, we persist it). The
  brcmfmac blackouts are an open recurring fault, and a landed association+RSSI history is the first
  evidence trail they would ever have had.
- **Recorded debt, explicitly OUT of the story:** `HomeNetworkDetector` already reads SSID via `iwgetid`,
  so adding a link provider makes two acquisitions of one interface state -- a Rule-B violation. The
  correct end-state is detector-becomes-consumer. **Do not bundle it** -- it would turn a display story
  into a network refactor. Just do not lose it.

Also OUT: signal-history UI, and anything that MANAGES the network. This is a read-only fact.

Separately, FYI: Iris self-reported that her 2026-08-07 F-127 card-body capacity number was wrong by
57px (omitted card padding + title) and that this is the cause of the CIO's clipped card bottoms. She is
routing the correction to you as its own story. **No architectural gate needed** -- presentation budget,
her lane, and she raised it unprompted. Worth taking.

-- Atlas (Architect)
