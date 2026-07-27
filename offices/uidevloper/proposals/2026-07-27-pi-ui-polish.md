# Pi Touch-UI — Polish Pass (shipped surfaces) — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-07-27 |
| **Status** | DRAFT — design-before-build (CIO reviews the mockup; then Marcus grooms) |
| **Brief** | Marcus 2026-07-27, item 3 ("close open polish items; make the shipped UI clean end-to-end") |
| **Companion** | `proposals/2026-07-27-pi-ui-polish.html` + hosted artifact |
| **Surfaces** | the SHIPPED `dashboard.{html,css}` + `carousel.js` (V0.29.16) — refinement, not redesign |
| **Palette** | `specs/UI/tokens.css` |

Three flagged items. All refine already-shipped, honest-instrument surfaces — no new data,
no new contracts. Each is a small, self-contained story.

---

## P-1 · System Status card — density + glanceability
**Now (shipped):** four tiles (OBD / Sync / Power / Drive) stacked vertically, each label + value
+ detail. Honest, but you must *read* all four to know system health — not glanceable.

**Polish:**
1. **A summary line at the top** — `SYSTEM · OK` (green) only when every source is genuinely good;
   otherwise the worst state, e.g. `SYSTEM · 1 ISSUE` (amber) / `RECONNECTING` (amber). Honest-
   instrument F-1: never green unless all-green. The glance answer lives here.
2. **2×2 tile grid** (the F-092 spec's original intent) instead of a 1-column stack — denser,
   fits the same content with room to breathe.
3. **A status dot per tile** (green/amber/red/neutral) so health reads by scanning four dots, not
   four paragraphs. The dot mirrors the existing per-tile `level` (no new state).
- Keeps every current value/detail; only the arrangement + the summary + dots are new.

## P-2 · System Setup menu access — long-press vs ⋮
**Now (shipped):** BOTH a 5 s long-press-anywhere (filling ring) AND a top-bar `⋮` open the menu
(service stop/restart, Exit-UI — consequential, each already behind a confirm).

**The tension:** `⋮` is discoverable but is a *single tap to a consequential menu* — easy to hit
by accident on a bumpy road. Long-press is deliberate (can't happen by accident) but undiscoverable.

**DECISION — Option C, context-aware `⋮` (CIO 2026-07-27). LOCKED.**

**Context-aware `⋮` (best of both):**
- **`⋮` shows only on the parked / idle home card** (discoverable, and you're stopped — safe to tap).
- **Hidden while driving** (the live card stays clean; no accidental menu in motion).
- **Long-press (5 s) always available** as the deliberate override, in any state.
- This leans on the idle/live state the UI already has — system-setup is a parked-context action.

**Alternatives (not chosen):**
- **(A) Long-press-only** — cleanest, safest, least discoverable (my earlier lean).
- **(B) Always-`⋮`** — the current shipped behavior; discoverable but a single consequential tap in motion.
- **(C) Context-aware `⋮`** — ✅ CHOSEN.

**Build note:** the show/hide keys off the idle/live state the UI already consumes (parked → `⋮`
shown, driving → hidden) — pure UI, no new data/contract. No Atlas gate expected.

## P-3 · DTC detail overlay — hierarchy + grouping
**Now (shipped):** hero · directive · caveat · status meta · freeze-frame/realtime fallback ·
severity-gated fix + trust badge · log/sync footer · gated Clear. All correct, but dense — it reads
as one long column; the "what do I do" isn't the first thing the eye lands on.

**Polish (pure presentation — no logic change):**
1. **Directive-first for 🔴/🟡** — the action band (`REDUCE LOAD · PULL OVER` / `GET DIAGNOSED`)
   moves directly under the code+chip hero, larger, so the glance answer is "what to do", then the
   detail. (🟢 keeps the calm "safe to clear once logged".)
2. **Card the sections** — Freeze-frame/context, Suggested fix + trust badge, and the Clear zone
   each become a bordered block with a small uppercase label, so the eye groups them instead of
   reading a wall.
3. **Consistent rhythm + bigger Back** — one spacing scale; the `‹ Back` gets a ≥40 px target and
   clear affordance so the operator is never unsure how to leave.
- No change to the severity gating, the fix-replacement safety rule (S-4), the trust badge, or the
  Mode-04 clear gate — this is typographic/layout hierarchy only.

---

## Acceptance criteria (Argus-style)
1. **P-1 glance:** System Status shows an honest summary (green only when all sources good) + a 2×2
   grid with a per-tile status dot; all shipped values/details preserved. ✅/❌
2. **P-2 access:** the chosen menu-access model is implemented; the menu is never reachable by a
   single accidental tap while driving; long-press still opens it; each destructive item still confirms. ✅/❌
3. **P-3 hierarchy:** the DTC detail leads with the directive for 🔴/🟡, groups freeze-frame/fix/
   clear into labeled blocks, and the Back target is ≥40 px — with zero change to gating/safety logic. ✅/❌

## Routing
- **Atlas:** none expected — all three are presentation-only over existing state (confirm P-2 if the
  context-aware `⋮` touches the kiosk lifecycle; I read it as pure UI). 
- **Spool:** none — no value semantics change.
- **Ralph:** builds after CIO review (design-before-build). Three small independent stories.
- **Marcus:** grooms alongside the live-cards work (these don't depend on US-478).
