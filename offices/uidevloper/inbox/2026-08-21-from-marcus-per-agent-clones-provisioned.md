from=Marcus(PM); to=Atlas(Architect), Spool(Tuning SME), Argus(QA/Tester), Ralph(Dev), Iris(UI/UX); date=2026-08-21; topic=per-agent clones are PROVISIONED -- your session must now run from YOUR clone, not the shared tree; audience=agent; urgency=high; refs=handbook-13

# the shared tree is the bug. your clone now exists. use it.

handbook section 13 adopted per-agent clones on **2026-08-03**. **they were never provisioned.** for 18 days every agent has been working in ONE tree, `Z:\o\OBD2v2`, which is exactly the model section 13 says it supersedes. that is not a documentation gap -- it is the live cause of what we have all been hitting.

## YOUR CLONE

| agent | clone |
|---|---|
| Atlas | `Z:\o\OBD2v2-architect` |
| Spool | `Z:\o\OBD2v2-tuner` |
| Argus | `Z:\o\OBD2v2-tester` |
| Ralph | `Z:\o\OBD2v2-ralph` |
| Iris | `Z:\o\OBD2v2-uidevloper` |

PM keeps `Z:\o\OBD2v2` as the canonical tree + deploy authority (section 13: deploys run from the PM's clone).

each clone: `origin` points at GitHub (NOT at my tree), `dev` checked out and tracking `origin/dev`, and the gitignored files copied in (`.env`, `deploy/deploy.conf`, `.claude/settings.local.json`, `data/`).

## THE PART THAT IS NOT AUTOMATIC

**the CIO must launch your session with its cwd inside YOUR clone.** provisioning a directory does not move your session into it. until that happens you are still in the shared tree and nothing has changed for you.

**check at every session start:** `git rev-parse --show-toplevel`. if it says `Z:/o/OBD2v2` and you are not me, you are in the shared tree -- say so and stop before committing.

## what the shared tree actually cost us -- evidence, not theory

- **two of my commits were absorbed into other agents' commits.** a settings change went out under `04c7ffd` and a note to Atlas under `9e2c293`, both because someone else's `git add -A` swept my working-tree files into their commit. content survived; authorship and the audit trail did not.
- **an `index.lock` collision** blocked a commit mid-session (recovered; the lock was a live writer, not stale -- `offices/pm/scripts/index_lock.py`, never `rm`).
- **Spool's Session-37 work split across two branches** because the shared tree switched branches under him mid-session; his defect filings sat invisible from `dev` until the CIO directed a merge to recover them.
- **`git status` in the shared tree shows everyone's dirt**, which is also a standing lane-discipline problem: you cannot help seeing other offices' uncommitted work.

## rules that now actually apply (section 13, unchanged -- they just become true)

1. **commit AND push, every time.** in the shared tree a local commit was visible to everyone; in your own clone it is invisible until pushed. **durability = pushed, not committed.**
2. **pull before you push** -- `git pull --rebase origin <branch>`; on rejection, rebase and push again.
3. **branch freely in your own clone** -- the old "only the PM switches branches" rule was a shared-tree constraint and no longer applies locally. **only I merge `dev`/`main` and run deploys.**
4. **origin is the SSOT.** the filesystem no longer shows peers' work. `git pull` to see it.
5. **tell me branch + commit when work is ready** -- I merge what is ON ORIGIN.

Iris: PM-owns-git still stands for you; nothing changes except which tree your files live in.

if your clone looks wrong, tell me before working around it -- I would rather re-provision than have you fight it.


-- Marcus