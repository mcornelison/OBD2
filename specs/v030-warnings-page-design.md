# V0.30 Warnings page + top-bar warning icon — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 (brainstorm 2026-10-12/13; **reworked 2026-10-13 for R31**) · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **§4.4 rewritten: the CIO kept the full-screen takeover (R31, Marcus 2026-10-13 14:41). My no-takeover design (WN-3) is superseded.**
**Mockup:** `proposals/2026-10-12-v030-warnings-page.html` → https://claude.ai/artifact/1hZxFmhcUM8rY5onGu8eXU (**layout A, scrolling, is the locked one**)
**DoD lines served:** 9 (warnings: top-bar icon on every page + own page), 8, 12 (carries US-754, US-758; ARCH-062)
**Builds on:** W-12 unified alert layer (Atlas ruling 2026-06-19: one arbiter-owned `alerts` view-state, an aggregator over providers; tier → live > stored → newest). Spool tiers: `specs/grounded-knowledge.md` DTC severity row + `tuner/dtc-display-clear-safety-advisory.md`.
**Canonical home:** `specs/` in the repo via a bench.

---

## 1. Purpose
**Everything that needs attention, ranked, in one place**, with an icon on every page so nothing can hide on a page you aren't looking at.

## 2. Decisions locked (CIO)

| # | Decision | CIO choice |
|---|---|---|
| WN-1 | Sources | **Trouble codes · live engine protection · system issues · data-capture stall** |
| WN-2 | Icon | **4 states + count**: none / not checked / WATCH / STOP |
| WN-3 | Full-screen takeover | ~~None (icon + page only)~~ **SUPERSEDED by R31 (CIO, asked directly 2026-10-13): an active red TAKES OVER the screen.** This is Spool's shipped US-484-b treatment, so no ratification is needed (Spool 15:10). |
| WN-4 | STOP signalling | **Takeover (§4.4) + pulsing red icon.** The one-time jump to Warnings is **dropped**: the takeover already owns the screen, so a jump underneath it does nothing. |
| WN-5 | Live engine protection | **In** (CIO first excluded it, then restored it once shown the gap: an overheat would otherwise show only on the driving page) |
| WN-6 | Clear-code flow | **Keep as shipped** (Mode 04, gated) |
| WN-7 | Order | **One list by severity** |
| WN-8 | Acknowledge | **Stops the pulse + the jump; the entry stays until its cause clears** |
| WN-9 | Layout | **A · Ranked list, showing ALL entries; scrolling allowed** |

## 3. Layout (480 × 320; body 258)

```
┌──────────────────────────────────────────────┐ top bar: … [▲3] (warning icon, every page)
│ 3 ACTIVE                     codes read 6:42 PM│ ~40  --fs-primary
├──────────────────────────────────────────────┤
│ [STOP ] Coolant 232 °F                  ENGINE │ ~50
│         Engine overheating. Pull over…    now │
│ [WATCH] Battery 12.6 V                  ENGINE │
│         Not charging while running.     2 min │
│ [WATCH] P0400                             CODE │
│         EGR flow fault. Get it checked soon.  │
│ [MINOR] P0443                             CODE │ ▓ scrollbar when more
│ ↓ 2 more below                                │
└──────────────────────────────────────────────┘
```

| Element | Tier | Note |
|---|---|---|
| Header | `--fs-primary` | `n ACTIVE` / `NONE` / `NOT CHECKED` (amber) + `codes read h:mm` `--fs-meta` |
| Chip | `--fs-meta` | STOP `--critical-red` · WATCH `--amber-warn` · MINOR `--green-ok` · UNRATED `--neutral-chip-bg` |
| Title | `--fs-label` mono | code or live value |
| Sentence | `--fs-meta` | instruction as **plain text** (US-758) |
| Source / age | `--fs-meta` | ENGINE · CODE · SYSTEM · DATA |

Entries ≥ 48 px tall. **All entries render; the list scrolls** with a visible scrollbar and an `↓ n more below` cue (no silent clip). Ranking means the most severe are always above the fold, so **nothing requires touch while driving** (R5).

## 4. Behaviour

### 4.1 Sources and ranking
| Source | What becomes an entry | Tier |
|---|---|---|
| **CODE** | stored/pending DTCs | Spool's table; **unknown ⇒ UNRATED, never a guessed tier** (US-754). Rated 2026-10-13 (Spool): **P0400 WATCH · P0430 WATCH · P0443 MINOR**. A new UNRATED code on the car is Spool's trigger to rate it; there is no speculative P0 table. |
| **ENGINE** (live) | coolant, battery voltage, intake air in a band, **with the dwell rules** | provider band (coolant red-first-sample bypass; intake air never above WATCH) |
| **SYSTEM** | whatever the System verdict counts (System spec §4.1) | WATCH |
| **DATA** | capture stalled while the engine runs (US-735), read from `capture-health.feeds` | WATCH. Engine-running predicate ratified (Spool 2026-09-21): accel_z σ > 0.10 for **N = 7** consecutive 10 s buckets (70 s; zero false positives in ~73 h parked). |

Order: **tier (STOP > WATCH > MINOR > UNRATED) → live before stored → newest first** (Atlas 06-19; Spool-confirmed). The **arbiter** orders; the page renders the order it is given.

### 4.2 Top-bar icon (every page)
| State | Condition | Look |
|---|---|---|
| none | checked this session, list empty | grey outline triangle |
| **not checked** | codes **not read this session** (ARCH-062) | amber `?`; **never looks like "all clear"** |
| WATCH | highest active is WATCH/MINOR/UNRATED | amber triangle + count (MINOR-only: grey-text count) |
| STOP | highest active is STOP | red triangle + count; **pulses until acknowledged** |
`prefers-reduced-motion` ⇒ no pulse; a steady red outline instead.

### 4.3 Empty states
- **Checked, nothing found:** `NO WARNINGS`, plus `Codes read at h:mm. Engine, system and data all clear.`
- **Not checked:** `? NOT CHECKED YET`, plus `Trouble codes haven't been read since key-on, so "nothing found" can't be claimed.`

### 4.4 STOP handling: full-screen takeover (R31)
**Superseded text:** the first version of this section had no takeover (pulse plus a one-time jump). The CIO kept R31 when asked directly on 2026-10-13, so an active red takes over the screen. Spool's 12:11 "no-takeover ratified" is void (his 15:10 note).

**Trigger.** The **top active STOP entry** in `states/alerts` (the arbiter decides; the page never compares a value). Today the only live red is coolant: **≥ 110 °C on the first sample, or ≥ 104 °C for ≥ 120 s** (band producer, R26).

```
┌──────────────────────────────────────────────┐ covers the top bar too; the REPLAY marker stays visible above it
│                                              │
│                PULL OVER                     │ --fs-hero, --critical-red
│                                              │
│              COOLANT 232 °F                  │ --fs-primary: name + value + unit
│     Engine overheating. Stop the engine.     │ --fs-label: the provider's sentence
│                                    12 s ago  │ --fs-meta: since firstSeenTs
└──────────────────────────────────────────────┘ full-bleed --critical-red frame, solid fill
```

| Rule | Detail |
|---|---|
| **Words, not colour alone** | Always the words **`PULL OVER`** plus the **value and its unit** (Spool 15:10 advice). Text survives a single glance; colour alone does not. |
| **Every page** | It covers **whatever page is showing**. R31 names the Driving page because it is the default, but a red must not hide on another page. That was the reason the old jump existed. |
| **Live red: not dismissable while active** | No control removes it while the provider reports `active` (Spool 06-18). No button is shown. Acknowledge (tap anywhere) stops the **icon** pulse only. |
| **Ends when the cause ends** | When the entry goes inactive, the takeover closes and the page underneath returns. The entry stays on Warnings until the arbiter drops it. |
| **Stored STOP code** | Uses the same surface (one takeover, W-12). Acknowledge **closes** it for that code, because a stored code is not damage in progress. A STOP code is never clearable here. |
| **Brightness** | **Full brightness while up**, independent of auto-dim. |
| **Motion** | The frame does a slow 2-step pulse. `prefers-reduced-motion`: a steady frame. |
| **Layering** | Above every page, menu and detail overlay. **Below the REPLAY marker only** (Sprint 98 review B-2): a replayed overheat must still say REPLAY. The marker is a direct child of `body` (not of `#topbar`, which is its own stacking context at z 10), with a z-index above the highest declared in `dashboard.css` (US-901-b, as folded by Marcus). `pointer-events` stay on the takeover, never on the marker. |
| **Touch** | Not required at any point (R5). |

Acknowledge is stored by the provider (`POST /alerts-ack`, Atlas §7), so a kiosk restart does not re-pulse.

### 4.5 Code detail + clear (as shipped)
Parked-only tap on a CODE entry ⇒ detail (directive-first, carded sections, freeze-frame realtime fallback). **Clear:** MINOR (clearable) codes only, hard confirm, re-read, refuse a second clear; never STOP/WATCH; gate re-checked at the action path (Atlas DTC-A1).

## 5. Data contract

| Need | Status | Owner |
|---|---|---|
| **`states/alerts`**, arbiter emitter in the orchestrator over CODE / ENGINE / SYSTEM / DATA; provider orders the list | **APPROVED to build in V0.30** (Atlas 2026-10-13 §7; provider story 4) | Atlas · Marcus story |
| Per alert `{id, source, tier, title, sentence, firstSeenTs, acknowledged, active}`; `id` = source + key | approved | Atlas |
| `codesCheckedThisSession`, `checkedAtTs` (last good Mode 03 this boot; null ⇒ `?`, ARCH-062) | approved, new | Atlas |
| Ack held by the provider: token-gated `POST /alerts-ack {id}`; clears when the condition ends | approved, new | Atlas |
| Live engine bands with dwell | band producer (R26); Spool's spec sent 2026-10-13 | Spool + Marcus |
| Generic P0 severity | **P0400/P0430 WATCH, P0443 MINOR rated**; others UNRATED | Spool |
| DATA source | `capture-health.feeds.<feed>.{state, firstSampleTs, lastSampleSecondsAgo}` + US-735 N = 7 | Atlas (provider story 2) |
| System issues | `system-status.verdict{issueCount, members[]}` (null is not an issue) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. Not-checked fixture: icon `?`, header `NOT CHECKED`, **no** "NONE"/"all clear" text anywhere.
3. Live-STOP fixture, opened on **each** page in turn: the takeover covers the page and shows the text `PULL OVER`, the value and its unit; the icon is red and pulsing. After acknowledge: no icon pulse, **takeover still up**, entry still listed.
4. Live-red fixture: no control removes the takeover or the entry while the provider reports it `active`. Flip `active` to false: the takeover closes and the page underneath returns unchanged.
4a. Stored-STOP fixture: acknowledge closes the takeover; the entry stays; no clear button.
4b. Takeover brightness is full regardless of the auto-dim level.
4c. Stylesheet assert (the render harness does no layout): the REPLAY marker's z-index exceeds the takeover's and every other declared z-index in `dashboard.css`, so a future overlay above it fails the suite.
5. Order equals the arbiter's order (fixture with mixed tiers/sources/ages).
6. 7-entry fixture: all 7 reachable by scroll; scrollbar + `n more below` visible; top entries are the most severe.
7. UNRATED code never renders a STOP/WATCH/MINOR chip.
8. No instruction text has button affordance (no border/fill/pointer cursor) (US-758).
9. Clear button absent for STOP/WATCH/UNRATED; absent while moving.
10. No literal colour or px in this page's CSS.
11. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`stop-live-overheat` (takeover) · `stop-live-cleared` · `stop-stored-code` · `two-stored-codes-real` (P0400 WATCH, P0443 MINOR) · `unrated-code` · `mixed-four-sources` · `checked-clean` · `not-checked` · `seven-entries-scroll` · `stop-acknowledged` · `voltage-watch-engine-off-gated` · `data-stall-n7` · `replay-stop-live`.

## 8. Out of scope
Knock alerts (need ECMLink) · AFR/lean numeric (no wideband) · oil pressure (no sensor) · audio alerts (US-538).

## 9. Open items
- ~~Spool: ratify §4.4~~ (moot under R31) · ~~US-754 for the car's codes~~ (rated) · ~~US-735 predicate~~ (N = 7). **Still Spool:** rate any new UNRATED code; the band story.
- **Atlas:** arbiter story 4 (approved). Confirm that a stored STOP code drives the same takeover as a live red (§4.4: one surface, ack closes it for a stored code only).
- **Marcus:** R31 scope. Does "active red" include a stored STOP code, or live reds only? This spec assumes both share one surface, with the dismiss rule split as in §4.4.
- **Mockup:** the published Warnings mockup still shows the no-takeover version; a takeover frame is owed in the next mockup pass.
