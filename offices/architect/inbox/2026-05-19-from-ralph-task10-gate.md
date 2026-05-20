From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 10 complete (last in-code task).
Design-gate requested; after PASS the sprint hands off to the CIO bench.**

## Task #
**Task 10** — `docs/phase2-deploy-and-acceptance-runsheet.md` rewritten to
the spec §10 acceptance gate sequence (strict order, paste-safe, post-
redeploy-aware).

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`1276f73`** (1 file,
+119/−55): `docs/phase2-deploy-and-acceptance-runsheet.md` fully rewritten.

The previous runsheet (2026-05-18, pre-bricking-incident) still referred
to the retired `UpsMonitor` VCELL heuristic as the trigger, said
"N cycles; CIO ratifies N; mirror Phase-1's 3", and had no recovery
procedure section. All of that is now corrected to the SS-T1..T9 reality.

## Pre-registered gate criteria — evidence

**#1 — Strict (a)→(e) order:**

| Section | Step | Implementation |
|---|---|---|
| §0 + §1 (preceding context) | Atlas sign-off lineage + preconditions | T1..T9 PASS table; Bench A + Bench B PASS as **established baseline** (not "to-do") with full evidence cited (Check A: hi×5→lo×4→hi×5→lo×7→hi×6→lo×4; Check B: `=1` confirmed + uptime≈5min post-repower) |
| §2 | **(b) Stays-up precondition** | "N consecutive clean boots on external power past `bootGraceSec + smoothingSec` (default 125 s); CIO ratifies N; Atlas suggests N=3 minimum." Framed as the regression net the 2026-05-18 bricking loop violated. |
| §3 Cycle A | **(c) On-battery cycles, graceful loop** | unplug → 5 s smoothing → bounded window → sync (reachable) or benign skip (unreachable) → graceful poweroff → unattended auto-boot |
| §3 Cycle B | **(c) On-battery cycles, abort paths** | smoothing-blip (restore <5 s, no window opens) + mid-window (restore <`totalCapSec`, window aborts). Both required ≥1× |
| §4 | **(d) Acceptance gate = 5 consecutive clean unattended cycles** | Explicit "5 consecutive" wording per your criterion #1d. Listed as the first checkbox of the acceptance gate. Plus the two Cycle-B variants, zero DOA-class journal errors, zero unprovoked self-shutdowns, Spool read-only sign-off. |
| §6 | **(e) Recovery procedure** | stop/disable/rm/daemon-reload one-liners. Explicit note that `mask` does NOT work (deploy installs a real unit file at `/etc/systemd/system/eclipse-powerwatch.service`) — the lesson from the 2026-05-18 bricking incident, preserved. Recovery one-liners are paste-safe (one SSH per command). |

**#2 — RUNNABLE on the actual bench, paste-safe (Check-A defect lesson):**
no heredocs, no multi-line over-SSH constructs. Every command is either
a single-line `ssh chi-eclipse-01 "..."` or a one-shot `ping`/local
command. Each long bash block uses separate-line one-shot `ssh` commands
to avoid the heredoc fragility class.

**#3 — Commands work against current state OR explicitly noted "after redeploy":**
the runsheet opens with a **blockquote callout**: "This runsheet operates
on the POST-REDEPLOY Pi. The current Pi runs the deployed V0.27.14
(`0125417`) code with the `eclipse-powerwatch` service *manually removed*
(post-bricking recovery, see §6). Marcus owns the redeploy decision and
timing (`/sprint-deploy-pm`); the deploy hazard stands until this drill
passes." §1 preconditions explicitly require the post-redeploy state
(`systemctl is-enabled eclipse-powerwatch.service` → `enabled`).

**#4 — Scope fence:** `git diff --stat 1276f73^! docs/`:
```
 docs/phase2-deploy-and-acceptance-runsheet.md | 174 +++++++++++++++---------
 1 file changed, 119 insertions(+), 55 deletions(-)
```
Exactly 1 doc file. **Zero code edits.**

**#5 — Atlas sign-off lineage cited:** §0 of the runsheet is a literal
table of T1..T9 + Bench A + Bench B with the inbox-note filenames as
provenance. Anyone reading the runsheet sees the full chain of gates
and the explicit statement that **chain unblock is now gated only on
this runsheet + the IRL drill itself.**

## Design invariants preserved
- **Honest empirical-gated language** (matching §11): bench gates are
  PASS; the 5-cycle IRL is the load-bearing acceptance; the runsheet
  does not assert beyond evidence (e.g., does not predict "drill will
  succeed" — it specifies what passing looks like).
- **The 2026-05-18 lessons are preserved as explicit guidance in §6:**
  `mask` doesn't work; the arm-self-check is the second safety net; the
  worst case of a wrong redeploy is "sequencer inert" not "Pi bricks."
- **Spool read-only sign-off** is on the acceptance checklist (data
  integrity intact across the drill).
- **The known interim-bounds tuning follow-up** (commit `d7849ce`) is
  flagged at sign-off as Spool's battery-runtime-data task — config-only,
  not blocking the 5-cycle drill.

## What this enables
After your gate PASS:
- Sprint 39 / V0.27.15 is **code-complete**.
- The sprint hands off to the CIO bench: redeploy (Marcus's lane, when
  the CIO directs) → §1 preconditions → §2 stays-up precondition → §3
  Cycle A ×5 + Cycle B ×2 → §4 acceptance gate.
- Chain unblock follows IRL acceptance; until then, deploy hazard stands.

## Gate request
Per the per-task discipline I **STOP here** and await your gate. This is
the **last in-code task** of the Shutdown Sequencer sprint. After your
PASS, Marcus closes out the sprint and the CIO bench takes over.

— Ralph
