# PM inbox archive

**Rule (CIO 2026-08-17): a message moves to `archive/YYYY-MM/` once it has been read and its action is closed.** The live inbox holds only messages that still carry an open action for the PM. Nothing is deleted — archived notes stay readable and stay in git history.

Layout mirrors Iris's convention (`offices/uidevloper/inbox/archive/`): one folder per month, named for the date prefix in the filename.

## 2026-08-17 sweep

Live inbox went **314 → 7**. Archived 315 notes (314 from the inbox root + 8 loose files that were sitting unfiled directly in `archive/`, now placed in their month folders).

| Month | Archived |
|---|---|
| 2026-04 | 59 |
| 2026-05 | 81 + 8 previously-loose + 27 pre-existing |
| 2026-06 | 62 |
| 2026-07 | 76 |
| 2026-08 | 29 |

**Basis, stated honestly:** the 2026-04 → 2026-07 notes (278) were archived on the strength of prior session closeouts recording them as resolved — `projectManager.md` tracks their outcomes through Session 58 — **not** on a fresh read of all 278 in this session. The 2026-08 notes were each checked against current `origin/dev` before archiving. If an older thread turns out to still be open, it is one `git mv` back.

## Kept LIVE — 7 notes, each with an open action

| Note | Open action |
|---|---|
| `2026-08-10-from-ralph-us543-data-quality-parity-needs-atlas-ruling.md` | **Awaiting Atlas ruling.** Rex implemented conditional (scope-limited) parity because literal `data_quality` set-equality would assert a falsehood across the B-104 tier split. Code shipped; the written AC still says "IDENTICAL". No reply found in any later note. |
| `2026-08-10-from-atlas-v0.29.28-review-plus-us543-contract-list.md` | The 6-assertion contract Rex is questioning — the other half of the same arbitration. |
| `2026-08-10-from-atlas-backlog-review-ordering-plus-5-additions.md` | US-544 (on-hardware gate), US-546-a/b (re-segmenter, F-128), US-547 (placeholder lint) still to groom. |
| `2026-08-07-from-iris-w16-sensor-prototypes-for-backlog.md` | W-16 P2 Engine card (MAF centerpiece) queued to groom. |
| `2026-08-08-from-iris-3p5in-legibility-bundle-for-groom.md` | Defines the open in-car acceptance (≥34px at arm's length) **and the ordering trap**: the check must happen AFTER US-552, and a bench look does not count. |
| `2026-08-07-from-atlas-3p5in-legibility-font-size-more-screens.md` | Same open in-car check — Atlas's font-size basis for it. |
| `2026-08-17-from-iris-CORRECTION-ltft-idle-rule-withdrawn.md` | Struck from `backlog.json` in `a274928`, but Iris notes the withdrawn rule still lives in the notes; must not resurface when W-16 / the P2 Engine card is built. |

## Archived this sweep despite being recent — verified closed against `origin/dev`

- `2026-08-17-from-iris-us532-branch-ready-to-merge.md` — `d7f1b03` is already an ancestor of `origin/dev`; her 4 ACs mirrored in `a274928`.
- `2026-08-17-from-iris-git-handoff-inbox-archive-and-pm-owns-git.md` — the 19-path hand-off landed in `75bd5ad`.
- `2026-08-17-from-atlas-unpushed-dev-commits.md` — all 4 flagged commits confirmed on `origin/dev`.
- `2026-08-15-from-atlas-pi-static-ip-done-move-deploy-to-hostname.md` — networking complete (`2ed9358`, `b376b63`); B-102/US-473 closed.
