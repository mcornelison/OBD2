# TD-067 / US-488 — Spool Per-Surface Red Ruling
**Date**: 2026-07-27
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (safety-signal integrity; no acute defect — STOP tier is clean)
**Refs**: TD-067, US-488, US-484-b, `dtc-display-clear-safety-advisory.md` §3/§6d, `specs/UI/tokens.css`

## The governing call (root cause TD-067 names)
TD-067 is right that the root is a **taxonomy↔display mismatch**: my severity model has three engine tiers (🔴 STOP / 🟡 WATCH / 🟢 MINOR) but surfaces used **brand-red as a generic "bad" color**. The fix is NOT a new red — it's routing every surface to its correct engine tier, and pulling **non-engine-state** things out of the engine color system entirely.

**REJECTED: a new `--degraded`/`--down` red.** On the narrow-gamut OSOYOO at arm's length, a second alarm-red is the exact brand-vs-alarm discrimination hazard S-2 exists to prevent. **Red = danger, one meaning only.** "Degraded / down / offline" is **amber** (`--amber-warn` already carries WATCH + degraded-escalation). Don't multiply reds.

**The clean line for `--critical-red`:** it marks a **critical, act-now STATE the system DETECTED** (engine STOP; imminent power-loss). It does NOT mark a **user ACTION** (a destructive confirm is a different axis — not a detected state).

## Per-surface ruling (all 10)

| # | Line | Surface | Ruling | Token |
|---|---|---|---|---|
| 1 | 66 | topbar glyph `data-state="down"` (link/service down) | Connectivity/plumbing degraded — NOT an engine danger. A dropped link painted pull-over-red is crying wolf. | **`--amber-warn`** |
| 2 | 157 | tile `data-level="down"` (degraded status tile) | Degraded system state, not danger. | **`--amber-warn`** |
| 3 | 176-177 | ladder `data-stage="TRIGGER"` + banner (battery failsafe TRIGGER) | Terminal, act-now critical STATE (imminent shutdown / data-loss). Genuine critical alarm — shares the alarm-red as a *system*-critical, not engine. **Copy stays system-appropriate, NOT "PULL OVER."** Earlier ladder stages (warn/pre-trigger) → amber. | **`--critical-red`** |
| 4 | 202-203 | ltft-bar `data-level="down"` (LTFT beyond ±10%) | Fuel-trim ±10% = classic **WATCH** ("investigate, drive gently") — NOT instant STOP. It escalates to 🔴 only when *correlated* with high load + lean O2 (the lean-under-load trigger in my advisory), which is a separate composite signal, not this single bar. | **`--amber-warn`** |
| 5 | 507 | `.detail-directive` (DTC detail band, ALL tiers) | **The real bug.** Painting the directive band one red for *every* severity means a MINOR gas-cap code shows a red directive — crying wolf — and a STOP code's directive reads inconsistent with its (now critical-red) chip/hero. Must be **tier-driven**, never blanket. No new token. | **tier-aware:** STOP→`--critical-red`, WATCH→`--amber-warn`, MINOR→`--green-ok` (or neutral text) |
| 6 | 569 | `#dtc-clear-result[data-level="reset"]` (code re-set after clear, §4d hard fault) | Meta-caution on the *clear action* — "it came back, stop chasing it." A persistent-fault WARNING. If the re-set code is itself STOP-tier, that STOP alarm independently owns the screen via its own severity — this banner needn't double it. | **`--amber-warn`** |
| 7 | 579 | `#clear-confirm .confirm-box` (Mode-04 confirm container) | **Destructive ACTION, not an engine alarm.** Mode 04 wipes every code + freeze frame + readiness monitors. Painting it `--critical-red` conflates "engine in danger" with "you're about to do something irreversible" — different meanings. Leaves the engine color system. | **new `--destructive`** (Atlas Rule-10 gate) |
| 8 | 581 | `#clear-confirm-ok` (Mode-04 confirm button) | Same — the destructive action itself. It's the *more* consequential sibling of the STOP-takeover's `#confirm-ok`; it must NOT share critical-red, or the two reds blur. | **new `--destructive`** (Atlas Rule-10 gate) |

## The one new token — my semantic constraints (value is Iris/Atlas's, not mine)
`--destructive` (for surfaces 7 & 8) — my hard constraints as safety-signal owner:
- **MUST NOT be any alarm-family red** (not brand `--red*`, not `--critical-red`) — the driver must never confuse "about to wipe codes" with "engine is dying."
- **MUST NOT be `--amber-warn`** — reserve amber for the engine WATCH tier; a UI action isn't an engine state.
- It's a **different axis** (action-consequence, not engine-state). Iris owns the visual treatment (I'd suggest a neutral-dark box + a distinct destructive accent, well clear of red/amber hue); Atlas gates the token. Route the value through them.

## Disposition summary
- **No new red.** 5 surfaces repoint onto existing tokens (1,2,4,6 → amber; 3 → critical-red) — no gate.
- **1 refactor** (surface 5 → tier-aware directive band) — no new token, Ralph change.
- **1 new token** (`--destructive` for 7,8) — Atlas Rule-10 gate; my constraints above.
- Extends the whole-file guard TD-067 suggests: after this, **no `var(--red*)` outside a brand-mark rule** should assert clean.

Routing the token-gate half to Atlas (A2AL). This closes the brand-vs-alarm cleanup. Ping at US-488 groom if any surface's actual `data-level` semantics differ from what the TD table implies.

— Spool
