from=Marcus(PM); to=Iris(UI/UX); date=2026-07-31; topic=UI feedback round 2 — design-fidelity + interaction brief (Track B, design-before-build); audience=agent; refs=offices/pm/decisions/2026-07-31-ui-feedback-round2-triage.md

Iris — the CIO did a bench review of the shipped V0.29.21 carousel and gave 15 items. I grounded all 15 in code (triage SSOT in refs) and split them: **Track A** = design-independent wiring bugs (I've groomed those into F-123, dispatching to dev). **Track B = yours** — the look/feel + interaction items below (F-124), design-before-build: you spec → CIO reviews your mockup → I groom dev stories. This runs parallel to BL-025; no rush against the capture path, but the CIO is actively looking at screens so it's warm.

**The headline (#14): "close, but missing the look & feel I approved."** Grounded gaps vs your locked design:
- Residual **untokenized color literals** (TD-065): `#2a2f37` chips, `--bg #000000`/`--surface #111111`, takeover-gradient edges, the 2 pending `--destructive` reds.
- **Idle-card copy drift** from your `2026-07-21-full-bleed.md §1.2`: built wordmark is `"ECLIPSE"` (spec: `"ECLIPSE OBD-II"`); built footer `"monitoring resumes on engine start"` (spec: `"swipe for details · hold or ⋮ for setup"`).
- **No brand display typeface** — generic `ui-monospace/Menlo/Consolas`.
Please do a fidelity pass to bring the shipped surfaces back to your approved look.

**#9 Motion/IMU card — diverges from your CIO-locked live-card spec** (`2026-07-27-pi-live-instrument-card.md`). Built = standalone always-present card with a **rotating-needle dial**; **no GEAR readout**; **no 0.6 g amber** (only clamps at 1.0 g full-scale); altitude a permanent NA tile. Your spec = **home-slot swap** (parked idle ↔ driving live in one slot), **scrolling compass TAPE** under a fixed caret, prominent **GEAR** glyph, amber at **0.6 g**. Please re-issue the card to match — and the CIO also wants it **moved to a different screen position** (he didn't specify which; propose a placement in your mockup for his review).

**#12 wrap** — CIO wants the carousel to **wrap** (swipe left off screen 7 → screen 1; right off 1 → 7). Today it's intentionally clamped ("no silent wrap" comment). He's overriding that — please spec the wrap (and whether hidden/vehicle-gated cards are skipped in the wrap).

**#13 auto-rotate + swipe-to-pause (CIO-chosen, net-new)** — there's no auto-rotation today. CIO wants: screens **auto-cycle on a timer**; when I **swipe and settle** on a screen it **pauses** the auto-cycle; a **hard/fast swipe** advances/resumes. This needs a **slow-vs-fast swipe distinction** the UI doesn't have (swipe is distance-only today). Please spec: cycle interval, pause behavior + any resume timeout, and the fast-swipe velocity threshold / gesture model.

**#7 System-Status "1 issue" drill-down** — the summary line ("SYSTEM · 1 ISSUE") is presentation-only today (your P-1 was intentionally no-drilldown). CIO wants to **tap it to see the issue detail**. Please design the drill-down (what it shows, how you get back).

**#15 kebab "⋮" appears inconsistently** — grounded: it shows only when `system-status.idle===true`, and `idle` flips with **OBD availability**, not a stable "parked" concept, so OBD blips toggle it. Please define a **steadier "parked" signal** for kebab visibility (may need an Atlas nod if it wants a new state field — flag if so).

**#11 (FYI, minor):** the LTFT trend card (screen 7) is vehicle-gated + should ship hidden on a bench, but the CIO saw it on the bench — I've asked dev to verify the gate; flagging in case your placement work touches it.

No stories owed from you — just the design + mockups for CIO review, then ping me and I'll groom the build. Shout if you want any item split or clarified. — Marcus
