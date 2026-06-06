# ECU-identity correction — SME-signed values for the seed fix (Ralph story)

**Date**: 2026-06-01
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Refs**: Atlas's blast-radius note to you; US-376 / US-374 (frozen seed literals); US-370; US-377 (V0.28.2 patch sprint)

## Context

CIO corrected the donor/current ECU's part number. Atlas already routed the **code/spec blast radius** to you (v0010/v0011 seed + architecture.md §5 + grounded-knowledge + memory). His note carries the architecture read; this note carries **the SME-authoritative values + writer disposition** so whatever you groom for Ralph is grounded and doesn't orphan drive FKs. I've already fixed everything in my own lane (cards, knowledge.md, grounded-knowledge, obd2-research, glossary).

## The correction (signed)

- **Current/donor ECU (drives ≥25, ECMLink unit):** `ecu_signature = MD326328`, `cal_signature = UNKCAL`, mfr P/N **E2T61683**.
- `MD335287` (what shipped in the `(MD335287, UNKCAL)` seed) was a **mis-ID** — same physical box, wrong number read off in Session 19 with no mfr code to cross-check. **Not a distinct unit, not a reflash.**
- **Prior STOCK ECU is unchanged:** `MD346675` / `6675` / mfr `E2T68273`.
- `cal_signature` **stays `UNKCAL`** — tune content never changed; CALID still unread (Mode 09 silent; needs an ECMLink USB read).
- **mfr code E2T61683** lives in my card / a `notes` field, **not the schema** this slice (the `ecu` table has no mfr-code column — confirmed with Atlas, not load-bearing for keying or calibration).

## Writer disposition for Ralph (the part that prevents data loss)

This is the **P/N twin of my Q5 `UNKCAL→CALID` ruling**: the box and its tune never changed, we only learned the correct service number. By the same discriminator — *"did the calibration content change?"* No →

- **Same-row UPDATE** of `ecu.ecu_signature` `MD335287 → MD326328`.
- **Preserve** that row's `correction_factor = 0.5` seed and **all drive FKs** pointing at it.
- **Do NOT mint a new `ecu` row** — a new row orphans the drive FKs and duplicates the identity on the `(ecu_signature, cal_signature)` pair-key.

If the fix rides as a migration: it's an in-place `UPDATE` of the existing seed row's `ecu_signature` (+ optional `notes` carrying `E2T61683`), not an INSERT.

## Governance note (yours to call)

The correct string `MD326328` collides with the **frozen US-376/US-374 seed literals** — a US-370-class freeze conflict. The **value is signed by me**; the unfreeze/sequencing (fold into US-377's V0.28.2 patch sprint, or a separate story) is your call. Atlas concurs it's an at-source pre-deploy correction that must land **before** `/sprint-deploy-pm` since nothing's deployed to prod yet on the V0.28.2 branch.

## Rationale / sources

- Corroboration: `MD326328` was already recorded as the sibling 97 non-EPROM ECMtuning part; `E2T61683` is fresh mfr-code evidence (same class as prior ECU `E2T68273`) — it cross-checks. Session-19 read-off had no mfr P/N to verify against.
- CIO direct identification 2026-06-01 (case label + mfr code).
- Card: `offices/tuner/cards/ecu-new-md326328.md` (authoritative, supersedes `ecu-new-md335287`).

— Spool
