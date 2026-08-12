# I-us540b — `specs/architecture.md` still documents the retired Health card

- **Filed by:** Ralph (Rex), Sprint 74 / V0.29.29, 2026-08-11
- **Story:** US-540-b (F-127) — re-lay the card set 4 → 6, Health retires
- **Owner requested:** Atlas (architecture SSOT) + PM
- **Severity:** docs-drift, no runtime impact — but it is **design-gate DoD** (PM Rule 10)
- **Why Ralph did not fix it inline:** `specs/` is read-only for Ralph
  (`offices/ralph/prompt.md` → PM Communication Protocol). Requesting the change
  here instead of editing, per that contract. Everything below is the exact edit.

## What happened

US-540-b retires the US-507 merged **Health** card and splits its three readouts
back into standalone cards, taking the carousel 4 → 6:

```
Home · Alerts · System Status · Battery · Fuel Trim · Light
```

Code, markup, stylesheet and tests all moved. `specs/architecture.md` did not,
so it now describes a card that no longer exists and a dispatch path that was
deleted. Three sites:

| Line (at filing) | Current text | Problem |
|---|---|---|
| `3713` | `\| **Health** (US-507) \| *(multi -- `data-states`)* \| always-present \| **per SECTION, see below** \|` | the card is gone; `data-states` is gone from the markup entirely |
| `3716–3721` | "The carousel is **four cards** as of V0.29.23…" | now six; the Alerts card also moved to **second** (US-541 ordering landed with this story's markup) |
| `3723–3747` | the whole "##### The Health card is MULTI-SOURCE (US-507 / F-124)" section | describes a retired container, its `data-states` fetch loop, and per-**section** availability |
| `4546–4548` | "**US-507 relocated the surface**: it is now the **"Fuel Trim"** section of the merged Health card, reached through `healthCardView()`/`renderHealthCard()` rather than a `data-state` dispatch." | both named functions were **deleted**; fuel trim is a `data-state="ltft-trend"` card again |

## The requested edit

**1. The card-model table (~3709–3714)** — replace the Health row with three
rows, and note the order:

| Card | `data-state` | Tier | Absence renders |
|---|---|---|---|
| **Home** (US-508) | *(none -- `data-idle-home`)* | always-present | **the idle face, see below** |
| Alerts (DTC) | `dtc` | always-present | **"no data -- codes not read"** |
| System Status (Pi Health) | `system-status` | always-present | `unavailable` |
| Battery | `battery-health` | always-present | "no data -- UPS feed absent" |
| Fuel Trim | `ltft-trend` | **vehicle-gated** | **"no engine data"** |
| Light | `light` | always-present | "no data -- light feed absent" |

**2. The count paragraph (~3716–3721)** — the carousel is **six cards** as of
V0.29.29. Keep the existing warning about the bare count being vacuous (it is
still true and still earns its place: the deploy-kit inventory test names every
slot, and as of US-540-b asserts them as an **ordered** list, because Alerts
moving to second is invisible to a set-or-count assertion).

**3. Retitle §"The Health card is MULTI-SOURCE" → "The three source cards
(US-540-b / F-127)"** and rewrite the body. The two load-bearing properties
SURVIVE the split and should stay documented, but their justification inverts:

- **Availability is resolved PER SOURCE.** The merge had to *fight* for this
  (one card-level check would have blanked two live instruments from one real
  fault). Split back out it is **structural** — a dead UPS cannot reach the
  Light card at all. The `SOURCE_CARDS` table in `carousel.js` is what keeps it
  a per-source route rather than a card-level branch.
- **The gate SPEAKS instead of hiding.** Fuel trim stays vehicle-gated and keeps
  the US-507 *wording* rather than reverting to the pre-US-507 `hidden`. The
  reason changed: US-540-b locks **six** cards, so a card that vanishes on a
  bench breaks the set exactly where the CIO reads the panel most days. The gate
  is still evaluated **before** the data, and a gated card carries no view at
  all, so a stale `ltft-trend` file from the last drive cannot paint a confident
  trim for an engine that is not running. Still ships `data-gated="true"` to
  fail closed before the first poll.

**4. The LTFT render paragraph (~4544–4554)** — replace the US-507 relocation
sentence with: US-540-b returned the surface to a standalone **"Fuel Trim"**
card reached by the normal `data-state` dispatch, through `sourceCardSpec()` /
`sourceCardView()` / `renderSourceCard()`. `healthCardView()` and
`renderHealthCard()` **no longer exist**. The retitle remains a LABEL change
only across all three arrangements — emitter, thresholds, classifier and the
insufficient guard are untouched, so Spool's LTFT semantics are preserved
exactly.

## Why this is worth an explicit issue rather than a silent TODO

The renamed functions are the trap. `healthCardView()` / `renderHealthCard()`
are cited in architecture.md as the dispatch path for fuel trim, and both were
deleted this story. A reader trusting the doc would go looking for a function
that is not there — and the *plausible* wrong conclusion (that fuel trim is
still special-cased through a multi-source path) is exactly the design US-540-b
removed. Stale architecture that names deleted symbols is worse than silence,
because it reads as authoritative.

## Verification the code side is actually done

- `git grep 'healthCardView\|renderHealthCard\|healthSection\|data-states' -- specs/UI src/ deploy/`
  → only `dashboard.css` (the retirement comment explaining why the block is
  gone, deliberate) and the two test files' **absence** assertions.
- `pytest tests/ui tests/deploy/test_dashboard_kit.py` → **774 passed, exit 0**.
