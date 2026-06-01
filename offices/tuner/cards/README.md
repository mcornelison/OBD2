# Vehicle Knowledge Cards — Schema & Conventions

**These cards are the single source of truth (SSOT) for facts about THIS specific 1998 Eclipse GST.**
They are the atomic, RAG-ingestable knowledge units for the MrSpool layer (see `../knowledge/mrspool-vision.md`).

- **One fact per card.** A card should make complete sense retrieved in isolation (no "see above").
- **`../vehicle.md` is a generated index into these cards** — a quick-reference, NOT a second copy. Authoritative values live here, in the cards.
- **`../knowledge.md` holds GENERAL tuning/DSM/4G63 craft** (how to read PIDs, knock theory, failure modes, glossary) — not THIS-car facts. It points to `../vehicle.md`.
- Cross-link related cards with `[[card-id]]`.

## Front-matter schema (required on every card)

```yaml
---
id: <stable-kebab-id>            # filename without .md; e.g. ecu-prior-md346675
title: <human title>
topic: ecu | timing-knock | fuel-trim | cooling | boost | fuel-system |
       obd2-capability | safe-ranges | failure-mode | mod-path |
       empirical-drive | maintenance | methodology
summary: <one line — fed into the vehicle.md index>
ecu: prior | new | both | n/a    # which ECU this fact applies to (prevents cross-ECU contamination)
mod_state: premod | <future enums as mods land>
fuel: 93-octane | n/a            # EXACT-locked where applicable
confidence: authoritative | observed | community | hypothesis
  # authoritative = CIO / manufacturer / [EXACT]; observed = this car's data;
  # community = DSMTuners consensus; hypothesis = unverified inference
status: current | superseded | archived-historical
  # retriever serves `current` by default; others only on explicit historical query
source: <drive_id | session | CIO-directive | DSMTuners-thread | ECMLink-doc | manufacturer-spec>
date: YYYY-MM-DD
exact_locked: true | false       # carries an [EXACT: …] DO-NOT-CHANGE value
supersedes: [<id>…]
superseded_by: <id | null>
---
```

`ecu` + `status` + `confidence` are the three fields that keep MrSpool from giving wrong-ECU, stale, or guess-as-gospel advice.

## Naming

`<topic>-<slug>.md` — e.g. `ecu-prior-md346675.md`, `drive-005-cold-warm-baseline.md`, `safe-range-coolant-temp.md`.
