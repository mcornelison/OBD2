from=Iris(UI/UX); to=Marcus(PM); date=2026-08-20; topic=topbar+chrome polish groom-ready + git handoff; audience=agent; urgency=medium

CIO bench review of deployed V0.29.29, 6 items. 5 presentation-only = GROOM-READY now, no gate.
1 needs an Atlas data contract = routed to him separately, do NOT bundle.

SPEC (the build spec, stories point at this):
  offices/uidevloper/proposals/2026-08-20-pi-topbar-and-chrome-polish.md
  + .html companion (before/after at true 480x320)

## GROOM NOW — no design gate (no state file / emitter / gate touched)

P-1 top bar layout. Glyphs left, clock CENTRE, version+kebab right.
  `#topbar` -> `grid-template-columns: 1fr auto 1fr`. Drop `margin-left:auto` off `#version-chip`.
  NB the existing US-542 comment argues against centring -- it is right about auto-margins
  (clock drifts w/ version-string length), wrong that this rules out centring. Grid fixes it
  structurally. Width-checked: ~328/460px used.

P-2 kebab overflows its own bar. `#menu-btn` = 40px box (`--tap-min`) + 34px glyph
  (`--fs-primary`) inside a 28px `#topbar`. Third dot paints outside the header fill.
  Fix = split VISUAL box from HIT box: paints bar-height @ `--fs-secondary`, transparent
  `::after{inset:-6px -7px}` keeps the S-2 40px tap target. Kebab is CHROME not a value, so
  the 34px driver-read floor never applied to it.
  SAME PATTERN, audit in-story: `#menu-close`, `#sys-detail-back` (both min-height:40 in
  36/44px heads).

P-3 the clipped card bottoms. **MY SPEC ERROR, not a build defect** -- flag it in the story
  so nobody hunts a regression. F-127 §3 budgeted ~258px of card body; it omitted card
  padding (28) + card title (39) and understated dots by 8 = **57px unaccounted**. Real body
  = 201px. 3 rows by my own row math = 202px -> overflows BEFORE any footer; +footer = 16-21px
  clipped = the CIO's "about 5%", on exactly the footer-carrying cards (Battery/Light/System/Alerts).
  Fix = reclaim CHROME, not type. topbar 28->34 (-6), dots 24->16 (+8), card pad 28->16 (+12),
  title ->`--fs-label`+6mg (+9) = **+23px -> body 224px**. 3 rows + footer = 222. Fits.
  EVERY driver-read value keeps its F-127 tier. This is a correction to the F-127 budget,
  NOT a reversal of F-127 -- if it ever looks like it needs a value shrunk, cut a fact instead.
  +2 DoD: (a) capacity ceiling = 3 rows + 1 footer, 4th fact -> drill-down; (b) NO SILENT CLIP
  -- content fits or the surface admits it doesn't. The overflow was invisible to everyone but
  the CIO's eye; that is the actual defect.
  ALSO: cheap discriminator for the story -- if the TOP edge of the top bar is also shaved it's
  US-552 panel overscan (KMS fix, not CSS). Ship P-3 either way, budget is wrong regardless.

P-4 system screens solid. `#setup-menu` .92 / `#sys-detail` .95 / `#dtc-detail` .95 -> opaque
  `var(--bg)`. Rule: navigational overlay = destination = solid; interrupting modal = scrim.
  `#confirm-modal` + `#clear-confirm` KEEP their scrim (regression guard in DoD).
  `#dtc-takeover` OUT OF SCOPE, severity styling untouched.

P-5 sync stamp. `syncTile()` pastes raw ISO `lastOkTs` -> `last 2026-08-17T19:30:28Z`.
  -> `Aug 17, 2026` / `7:30:28 PM`, LOCAL. Not cosmetic: top-bar clock is local, stamp is UTC
  = two clocks on one panel that can disagree by hours w/ no way to tell which lies.
  CIO call 08-20: full stamp own line ON the tile; `N rows · N pending` MOVES to `#sys-detail`.
  DoD musts: ONE 12-hour rule in carousel.js (shared helper; `fmtClock`'s own comment already
  warns about two formatters drifting) · unparseable -> raw string, NEVER `Jan 01 1970`/`NaN`
  (fabricated date on the tile that reports sync health = green-when-broken) · null -> `never`
  unchanged. Emitter keeps emitting ISO -- consumer formats, never re-derives. SSOT unchanged.

Suggested split: 4 stories = P-1+P-2 (top bar) · P-3 (own story, real regression surface) ·
P-4 · P-5. Acceptance on all = IN-CAR arm's length, seated. P-3 shipped through a bench check
in the first place because the arithmetic was wrong on paper and the bench never contradicted it.

## NOT YOURS YET
P-6 real WiFi glyph (CIO chose a genuine indicator over relabelling the sync arrow).
`system-status` has NO network key -> new emitter field -> Atlas gate first.
Filed: architect/inbox/2026-08-20-from-iris-wifi-glyph-contract-gate.md
Do not groom until he rules. P-1's grid already absorbs it w/ no re-layout when it lands.

## GIT HAND-OFF (I don't commit -- CIO 2026-08-17)
NEW this session:
  offices/uidevloper/proposals/2026-08-20-pi-topbar-and-chrome-polish.md
  offices/uidevloper/proposals/2026-08-20-pi-topbar-and-chrome-polish.html
  offices/pm/inbox/2026-08-20-from-iris-topbar-chrome-polish-groom-ready.md   (this)
  offices/architect/inbox/2026-08-20-from-iris-wifi-glyph-contract-gate.md
MODIFIED:
  offices/uidevloper/claude.md   (W-19 + session log)

STILL UNCOMMITTED FROM 2026-08-17 -- please pick these up in the same commit:
  offices/uidevloper/claude.md (charter §5 "Git -- I DON'T" row + §6 rewrite + W-17/W-18)
  offices/uidevloper/.claude/skills/closeout-session-iris/SKILL.md (Phase 5 -> hand-off)
  offices/uidevloper/inbox/ -- 16 notes moved to inbox/archive/2026-05|06/ (D + untracked dir)
Verified this session: `dev` is 0/0 vs origin and `iris/us532-settings-4-settings` (8b56841)
is contained in dev -- so the US-532 line IS durable. It is only the working-tree files above
that are not. Includes the charter edit that encodes the rule that you own my git.

-- Iris
