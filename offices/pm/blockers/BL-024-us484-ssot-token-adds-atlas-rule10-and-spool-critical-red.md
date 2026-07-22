# BL-024: US-484 blocked -- SSOT token ADDS unblessed (Atlas Rule-10 `text-primary` + Spool/Atlas `critical-red`)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium (one AC is SAFETY-signal) |
| Status       | Active                    |
| Blocking     | US-484 (Rule-10 token reconciliation, Sprint 61 / V0.29.15) |
| Waiting On   | (1) Atlas Rule-10 gate: ADD `--text-primary` to `specs/UI/tokens.css` with a grounded value. (2) Spool: assign `--critical-red` value + semantics; then Atlas gates that token. |
| Created      | 2026-07-22                |

## Description

US-484 is the highest-priority unclaimed, non-blocked story in Sprint 61
(US-483 is already blocked -- BL-023). It reconciles the shipped
`specs/UI/dist/dashboard-pi/dashboard.css` `:root` against the visual SSOT
`specs/UI/tokens.css`. Atlas Q-2 confirmed 3 drifts; only ONE is buildable now.
2 of the 4 acceptance criteria require **adding tokens to the SSOT**, which
`tokens.css` itself forbids doing without Atlas (and, for the alarm red, Spool):

Ground truth checked before filing (values read from the two files today):

- **AC1 -- green reconciliation: BUILDABLE NOW, not blocked.** SSOT already
  carries the blessed value: `tokens.css:37 --green-ok: #35C46A` (added per Atlas
  gate A-8). `dashboard.css:23` still uses the drifted `--ok-green: #2ECC71`
  (name AND value fork). Repointing dashboard.css `--ok-green` -> SSOT
  `--green-ok` is fully specified -- no design decision needed.

- **AC2 -- `text-primary`: BLOCKED on Atlas (Rule-10 token ADD).**
  `dashboard.css:16` invents `--text-primary: #DDDDDD`. The SSOT explicitly does
  NOT tokenize it: `tokens.css:64-67` -- *"Not yet tokenized (intentionally -- no
  grounded value exists yet) ... --text-primary (no surface has defined a primary
  text color above --text-secondary)."* The AC says *"SET it in the specs/UI SSOT
  with a grounded value (Iris proposes ... Atlas gates the token add)."* Adding a
  new token to the SSOT routes through Atlas under Rule-10 (`tokens.css:9-12`).
  No such ruling is in `offices/ralph/inbox/` (newest item 2026-07-04, predates
  this sprint).

- **AC3 -- `critical-red`: BLOCKED on Spool (value/semantics) + Atlas (token). SAFETY.**
  `tokens.css:59-60` declares `--critical-red: TBD` RESERVED, and
  `tokens.css:56-57` states *"surfaces MUST NOT render these until a value is set
  (route through Spool for semantics + Atlas for the token)."* Today the DTC STOP
  tier + takeover render in the BRAND red `--red-light #F61D2D`
  (`dashboard.css:214 #dtc-ribbon[data-level="stop"]`, `:380 .dtc-chip[data-level="stop"]`,
  `:395 .dtc-hero[data-level="stop"]`, `:362 #confirm-ok`) -- exactly the
  brand-vs-alarm collision the SSOT warns against (`tokens.css:44-51, 70-78`,
  Spool S-2). The AC requires assigning the Spool safety-red value, Atlas-gating
  the token, THEN repointing the STOP tier off `--red-light`. I must not pick a
  safety-signal red myself (Refusal Rule 2 -- Ground Every Number; this is the
  one that tells the driver "PULL OVER").

The story's own `conditionalOutcomes` confirm the critical-red gate ("Spool
assigns the value/semantics + Atlas gates the token BEFORE the STOP-tier repoint
-- do NOT pick a red yourself"). It notes green + text-primary "are not blocked
on Spool" -- true, but `text-primary` is still blocked on **Atlas** (Rule-10
token add), so only the green reconciliation can actually land.

## Impact

- **1 story stalled** (US-484, size M). The sprint is NOT fully blocked:
  US-485 (pygame status_display.py sunset), US-486 (2 red startup_log tests --
  fully buildable), US-487 (US-479 gate hardening) remain buildable. Ralph
  continues the loop on the next available story; no `SPRINT_BLOCKED`.
- Note this is the SECOND consecutive top-of-priority story gated on external
  design authority (US-483 on Atlas Q-4, US-484 on Atlas Rule-10 + Spool). The
  sprint's two highest-priority remaining items both need design rulings, not
  code. Surfacing both so PM can batch the Atlas/Spool asks.

## Attempted Solutions

- Read both files today: confirmed `--green-ok #35C46A` present in SSOT (AC1
  buildable), `--text-primary` intentionally un-tokenized in SSOT (AC2 gated),
  `--critical-red TBD` RESERVED with a MUST-NOT-render guard (AC3 gated).
- Searched `offices/ralph/inbox/` for any Atlas Rule-10 / `text-primary` /
  `critical-red` / Spool safety-red ruling for this sprint: none present.

## Proposed Resolution

PM (Marcus) / Atlas / Spool to pick one:

- **(A) Get the two token blessings, then build the full story.** Atlas ADDs
  `--text-primary` to `tokens.css` with Iris's grounded value (contrast on dark
  bg; `#DDDDDD` proposed). Spool assigns the `--critical-red` value + semantics
  (SSOT target `~#D32F2F`, cooler/orange-shifted from brand red) and Atlas gates
  the token. Ralph then: reconciles green, repoints `text-primary` to the SSOT,
  and repoints the DTC STOP tier + takeover off `--red-light` onto
  `--critical-red`. **Preferred** -- delivers the whole story incl. the
  brand-vs-alarm safety fix.

- **(B) Descope US-484 to the ungated green slice this sprint.** Ship only AC1
  (reconcile `--ok-green #2ECC71` -> SSOT `--green-ok #35C46A`, name + value, no
  visual regression). Defer `text-primary` (AC2) and the `critical-red` STOP-tier
  repoint (AC3/AC4) to a follow-up once Atlas + Spool bless the tokens. Requires
  PM to rewrite the ACs so the reduced scope reaches `passes: true`. NOTE: the
  brand-vs-alarm collision (a SAFETY-signal item, open since 2026-06-19) stays
  OPEN under this path -- call that out to CIO before choosing it.

Either path unblocks. Until one is chosen, US-484 stays `status: blocked` in
`sprint.json` so the loop advances to the next available story (US-485).

## Resolution

[Fill in when resolved]
