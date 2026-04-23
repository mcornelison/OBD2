---
from: Ralph (Rex, Agent 1)
to: Marcus (PM)
date: 2026-04-21
re: US-215 — TD-019/020/021/022 close-audit bundle
status: complete, passes:true
---

## TL;DR

**Audit finding: no TD files exist for TD-019/020/021/022. None ever filed.**
All four IDs are informal references that originated in Session 22 grooming
notes and auto-memory carry-forward, never graduated to formal tech_debt/ files.
Prior Ralph session (progress.txt:6772) had already noted this; US-215 was
seeded anyway because auto-memory still carried "formal close not verified."

Story passes outcome-based: **the pygame hygiene backlog is clean, because
there are no open TDs to close.** No retroactive TDs filed (per CIO drift-
observation rule: post-hoc TDs for never-filed informal references add noise
without signal). Findings documented in `specs/architecture.md` §10 closure-audit
subsection and mirrored in `offices/ralph/knowledge/session-learnings.md`.

## Per-ID disposition

| ID | Concern | Disposition | Evidence |
|----|---------|-------------|----------|
| TD-019 | DISPLAY / XAUTHORITY / SDL_VIDEODRIVER env vars | **Resolved by US-192** | `deploy/eclipse-obd.service:67-69` ships the env block. `specs/architecture.md:1155-1167` documents it. Session 22 symptom no longer reproducible. |
| TD-020 | pygame on tty console (no-X) | **Moot in production** | Pi-in-car auto-starts X via lxsession; tty-only is not a production target. Dev-only concern not carried forward. |
| TD-021 | Multi-HDMI dev workflow (xrandr force primary) | **Moot in production** | Single-HDMI production config; dev-only note. |
| TD-022 | `--no-binary :all:` pygame rebuild fails on Python 3.13 | **Deferred — wheel path is production** | SDL2 wheel-bundled pygame is the production install path; `--no-binary` is nice-to-have for kmsdrm work and not blocking. |

## Evidence

```
# TD files absent
$ ls offices/pm/tech_debt/TD-0{19,20,21,22}*
(no matches)

# Git history confirms never-created
$ git log --all --oneline --diff-filter=AD -- \
    'offices/pm/tech_debt/TD-019*' 'offices/pm/tech_debt/TD-020*' \
    'offices/pm/tech_debt/TD-021*' 'offices/pm/tech_debt/TD-022*'
(empty output)

# US-192 env block live
$ grep '^Environment=' deploy/eclipse-obd.service | grep -E 'DISPLAY|XAUTHORITY|SDL_VIDEODRIVER'
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mcornelison/.Xauthority
Environment=SDL_VIDEODRIVER=x11

# Prior-session audit confirmation
offices/ralph/progress.txt:6772 (Session 72/pre-Sprint 15 review note):
  "Audit TD-019/020/021/022: no files exist under `offices/pm/tech_debt/TD-019*..022*`.
   These were informally-named Session 22 pygame-hygiene items, never formally filed.
   No action required."
```

## Files touched

- `specs/architecture.md` — added §10 "Session 22 pygame hygiene — closure audit (US-215)" subsection with per-ID disposition table + rationale for not filing retroactive TDs.
- `offices/ralph/knowledge/session-learnings.md` — added "TD Close-Audit Pattern (US-215, 2026-04-21)" section capturing the ls-first + git-diff-filter verify flow and the "informal references in auto-memory are not contracts" lesson.
- `offices/pm/inbox/2026-04-21-from-ralph-us215-td-audit-complete.md` (this file).
- `offices/ralph/sprint.json` — US-215 `passes: true` + `completionNotes` flagging premise drift.
- `offices/ralph/ralph_agents.json`, `offices/ralph/progress.txt` — standard close-out.

## Files deliberately NOT touched

- `offices/pm/tech_debt/TD-019*..022*.md` — files do not exist; listing them in
  `scope.filesToTouch` was premise drift in the story manifest. No creation
  attempted per CIO drift-observation rule.
- `deploy/eclipse-obd.service` — `scope.doNotTouch` explicitly excluded; US-192
  shipped current state, audit is annotation-only.
- `src/pi/display/` code — out of scope (audit + annotate only).
- `requirements-pi.txt` — out of scope.

## Auto-memory suggestion

Line in `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`:
> "TD-019/020/021/022 pygame hygiene — some rolled into US-192 but formal close not verified"

Recommend updating to: **"TD-019/020/021/022 pygame hygiene — audited US-215
(2026-04-21), never formally filed; US-192 resolved the env-var concern,
others moot or deferred. Closure documented in specs/architecture.md §10."**

I don't edit auto-memory directly; flagging for your next PM-session closeout.

## Premise drift for grooming discussion

Story seeded against auto-memory-referenced TD IDs without a pre-flight check
that the TD files exist. Verification in grooming could catch this cheaply:
`ls offices/pm/tech_debt/TD-NNN*.md` before a close-audit story enters sprint.

Not a blocker — outcome is clean — but `sprint_lint.py` gaining a "verify
`scope.filesToRead` files exist for close-audit story types" check would
prevent the drift at manifest-time.

## Unblocks

Nothing gated on US-215. Sprint 16 remaining available-work per my Sprint
Status Summary below.

---
Ralph (Rex, Agent 1) — 2026-04-21
