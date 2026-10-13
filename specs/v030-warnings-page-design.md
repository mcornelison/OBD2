# V0.30 Warnings page + top-bar warning icon — design spec

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 (brainstorm 2026-10-12/13) · **Status:** CIO-APPROVED design, awaiting V0.30 DoD + grooming. **§4.4 (no takeover) awaits Spool's ratification.**
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
| WN-3 | Full-screen takeover | **None** (icon + page only), **⚠ reverses Spool's shipped STOP treatment (US-484-b), so it needs his ratification** |
| WN-4 | STOP without takeover | **Pulsing red icon + one jump to the Warnings page** |
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
│ [UNRATED] P0400                           CODE │
│         EGR flow fault. Severity not rated…   │
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
| **CODE** | stored/pending DTCs | Spool's table; **unknown ⇒ UNRATED, never a guessed tier** (US-754) |
| **ENGINE** (live) | coolant, battery voltage, intake air in a band, **with the dwell rules** | provider band (coolant red-first-sample bypass; intake air never above WATCH) |
| **SYSTEM** | whatever the System verdict counts (System spec §4.1) | WATCH |
| **DATA** | capture stalled while the engine runs (US-735) | WATCH, **blocked on Spool's engine-running predicate** |

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

### 4.4 STOP handling (⚠ Spool ratification required)
- On a **new** STOP: the carousel **jumps to Warnings once** and the icon pulses.
- **Acknowledge** (tap the icon or the entry, any time, never required) stops the pulse and suppresses further jumps **for that alert**. The entry stays.
- **A live red cannot be removed while active** (Spool 06-18). A stored STOP code stays until cleared by a scan tool (STOP is never clearable here).
- **No full-screen takeover.** Spool's US-484-b STOP integrity used several channels at once (area + motion + text + full brightness). This design keeps **motion** (pulse), **text** (the instruction), **colour**, and **position** (auto-jump), and drops **area**. **Full brightness on STOP is kept** (independent of auto-dim). **Spool rules whether that is enough.**

### 4.5 Code detail + clear (as shipped)
Parked-only tap on a CODE entry ⇒ detail (directive-first, carded sections, freeze-frame realtime fallback). **Clear:** MINOR (clearable) codes only, hard confirm, re-read, refuse a second clear; never STOP/WATCH; gate re-checked at the action path (Atlas DTC-A1).

## 5. Data contract

| Need | Status | Owner |
|---|---|---|
| **Unified alert arbiter + `alerts` state** (W-12 DELTA-1; approved 06-19, deferred until a live source existed; now four sources) | **not built** | **Atlas design · Marcus story** |
| `checkedThisSession` + `checkedAt` for codes (ARCH-062) | **new** | Atlas |
| Per-alert `acknowledged` + `firstSeen` (drives pulse + one-time jump) | **new** | Atlas |
| Live engine bands with dwell | Spool's unfiled band story (driving spec §5) | **Spool + Marcus** |
| Generic P0 severity (P0400) | **missing** (US-754) | **Spool** |
| Capture-stall predicate (US-735) | **blocked**: engine-running rule | **Spool** |
| System issues | System verdict provider (System spec Y-6) | Atlas |

## 6. Acceptance criteria (draft)
1. Fixtures render per §4 at 480×320 (screenshot).
2. Not-checked fixture: icon `?`, header `NOT CHECKED`, **no** "NONE"/"all clear" text anywhere.
3. STOP fixture: icon red + pulsing on every page; a page other than Warnings switches to Warnings **exactly once**; after acknowledge, no pulse and no further jump, entry still listed.
4. Live-red fixture: no control removes the entry while the provider reports it active.
5. Order equals the arbiter's order (fixture with mixed tiers/sources/ages).
6. 7-entry fixture: all 7 reachable by scroll; scrollbar + `n more below` visible; top entries are the most severe.
7. UNRATED code never renders a STOP/WATCH/MINOR chip.
8. No instruction text has button affordance (no border/fill/pointer cursor) (US-758).
9. Clear button absent for STOP/WATCH/UNRATED; absent while moving.
10. No literal colour or px in this page's CSS.
11. **DoD (R15): CIO judgement in the car.**

## 7. Fixtures
`stop-live-overheat` · `two-stored-codes-real` (P0400 unrated, P0443 minor) · `mixed-four-sources` · `checked-clean` · `not-checked` · `seven-entries-scroll` · `stop-acknowledged` · `voltage-watch-engine-off-gated`.

## 8. Out of scope
Knock alerts (need ECMLink) · AFR/lean numeric (no wideband) · oil pressure (no sensor) · audio alerts (US-538).

## 9. Open items
- **Spool:** ratify §4.4 (no takeover); generic-P0 severity (US-754); engine-running predicate (US-735); band story.
- **Atlas:** build the arbiter (W-12 DELTA-1) with not-checked, acknowledged and first-seen.
- **Marcus:** arbiter + band producer are V0.30 stories; WN-3 is a safety-rule change pending Spool.
