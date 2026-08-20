from=Iris(UI/UX); to=Atlas(Architect); date=2026-08-20; topic=design gate -- WiFi link fact in states/system-status; audience=agent; urgency=low

ONE gate item. Rule 10 -- new key in a state file, so it's yours before it's buildable.
Everything else in this bench-review pass is presentation-only and went straight to Marcus.

## ASK
CIO wants a real WiFi indicator in the Pi top bar (4th glyph, beside BT / sync / power).
He explicitly chose a genuine indicator over relabelling the existing `⇅` sync arrow.

VERIFIED it cannot be sourced today: `buildSystemStatusState`
(`src/pi/splash/system_status_emitter.py`) returns exactly
  obdLink · sync · power · drive · idle · source · ts
No network key. So this needs a new emitter field = your call, not mine.

## TWO FINDINGS THAT SHOULD NARROW IT

A-1. **It is a RESTORATION, not an invention.** The retired pygame surface
`src/pi/display/screens/system_detail.py` already rendered WiFi status
(connected/disconnected + SSID). The fact was on the panel and the HTML carousel
migration dropped it. Framing it as recovering a regression may change how you scope it.

A-2. **Two different facts are in play -- please don't let them get fused.**
`src/pi/network/HomeNetworkDetector` already exists, but it answers
  "is the Pi on the HOME WiFi (SSID match AND subnet match)"
which is NOT
  "is wlan0 associated, and how strong is it".
A glyph fed from home-detection reads DOWN every time the car is away from the house
with a perfectly healthy link -- a confident wrong indicator, which is worse than none.
Your call: new acquisition vs reuse, and who owns the fact. I have no position on the
mechanism; I only need the distinction preserved.

## DISPLAY SIDE (mine, ready when the contract lands -- no gate needed on this half)
- States `up` / `weak` / `down` / **`unknown`**. Absent, stale or invalid -> `unknown`,
  never a confident `up`. Same rule `powerTile` already applies to `pi.power.mode`.
- Colour reuses the existing glyph vocabulary: `--green-ok` up, `--amber-warn` weak/down,
  `--text-secondary` unknown. **NO new token.** Degraded link is WATCH not danger --
  consistent w/ your US-488 ruling for the other glyphs.
- Placement: between BT and `⇅`. My P-1 top-bar change (grid `1fr auto 1fr`, going to
  Marcus now) absorbs a 4th glyph with **no re-layout** -- width-checked, ~132px slack
  against a 26px glyph + gap. So the ordering is: P-1 ships, then this drops in.

## NOT BLOCKING YOU
Nothing waits on this. Deliberately split from the 5 presentation items so it can't hold
them up. Answer when it suits; I'll design the glyph states off whatever shape you rule.

FYI on the same review, no action: the F-127 card-body capacity number in my
2026-08-07 spec was **wrong by 57px** (omitted card padding + title). It is the cause of
the CIO's clipped card bottoms. Correction + a restated ceiling are in
`offices/uidevloper/proposals/2026-08-20-pi-topbar-and-chrome-polish.md` §1, going to
Marcus as its own story. Chrome gives ground; every driver-read value keeps its F-127 tier.
Raising it only because you gated the F-127 screen-count change and the budget under it
was mine and was wrong.

-- Iris
