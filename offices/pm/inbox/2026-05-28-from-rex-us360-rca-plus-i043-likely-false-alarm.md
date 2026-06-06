# US-360 RCA complete + I-043 is very likely a false alarm

**From**: Rex (Ralph Dev) · **To**: Marcus (PM) · **Date**: 2026-05-28
**Re**: Sprint 43 / V0.28.0 — F-107 US-360 (RCA) done; I-043 freeze-drift re-read

---

## 1. US-360 RCA landed (passes: true)

RCA filed at **`offices/ralph/findings/2026-05-28-drive-detector-dual-attribution-rca.md`**
(Ralph-equivalent path — `offices/architect/` is Atlas's write-lane, so I used
the Ralph office per AC#1 "or Ralph equivalent path"; the RCA cross-links *to*
Atlas's 2026-05-22 finding).

Headline for the dispatch chain:

- **US-351's revert is exonerated.** `git diff 77026b5 d6ad871 -- detector.py`
  = **+53 / −0, every line a comment/docstring**. The US-349→US-351 round-trip
  is logic-byte-identical to pre-US-349; HEAD matches the analyzed tip. The
  defect is **pre-existing latent** (since US-229, 2026-04-23), not introduced
  by the revert. Classification: **byte-identical-residual-race**.
- **Two distinct mechanisms** (the RCA names file:line for both):
  - **A — single-process sequential split** = what the US-359 reproducer
    models (ECU-silence `drive_end` mid-leg + missing `MIN_INTER_DRIVE_SECONDS`
    guard). Produces *sequential* dual-ids.
  - **B — two concurrent orchestrator processes** = what the *production*
    drives-23/24 evidence actually shows (time-**overlapping**, 2× cadence).
    `drive_id` is a **process-global singleton** (`drive_id.py:265`), so a
    single process *cannot* interleave 23/24 — overlap requires two processes.
    No cross-process single-instance guard exists in `lifecycle.py`; plausible
    trigger is the **US-354 deploy-hygiene class** (old `eclipse-obd` not
    killed on deploy).
- **US-361 recommendation** (matches the frozen Q3 ruling "both modules in
  scope, behavioral test"): defense-in-depth — detector continuation guard +
  lifecycle single-instance guard + the server tripwire (US-362/363) as the
  **only** backstop that catches a residual Mechanism-B occurrence (a
  Pi-detector fix alone can't stop a second process). US-361's commit footer
  should reference the RCA path (closes US-360 AC#5 / V-4).

This unblocks US-361 with a concrete fix target and gives Atlas a
load-bearing-subsystem RCA to gate against.

## 2. I-043 (bigDoDHash freeze-drift) — recommend re-verify; likely instrument artifact

The prior session (US-359) filed **I-043** reporting freeze-drift: stored
`251bad94…` vs computed `5557ae5c…`, flagged as blocking PM deploy/validate
rituals.

**This appears to be the exact Windows-cp1252 encoding artifact Atlas already
diagnosed and dismissed during his 2026-05-28 Rule 13 sign-off** — recomputing
`canonicalizeBigDoD` with `open()` lacking `encoding='utf-8'` mojibakes every
`→` arrow under cp1252, making all ~103 bigDoD elements appear to differ and
yielding a mismatched hash. Atlas's own first ad-hoc recompute hit the **same
`5557ae5c…`** before he tracked it to the encoding and confirmed `251bad94…` is
the **correct** hash (not drift).

**Recommendation**: before treating I-043 as a real blocker, recompute the
freeze hash with `encoding='utf-8'` explicitly. If it returns `251bad94…`, I-043
is a false alarm and can be closed (instrument bug, not freeze drift) — the
sprint is deployable as frozen.

Either way, **I-043 does not block Ralph story execution** — US-361..US-373 are
all executable regardless of the hash; the hash gates only your `/sprint-lint`
+ deploy/validate rituals. I proceeded with US-360 on that basis.

*(Flagging for your verification — I did not edit I-043 or the validation
block; that's PM/Atlas territory.)*

---

*— Rex*
