---
name: SemVer convention -- major.minor.patch with major=0 until first stable release
description: Project uses SemVer (major.minor.patch) for deploy/RELEASE_VERSION. Major stays 0 until CIO declares first stable working version (then bumps to V1.0.0). Minor bumps at every sprint close. Patch bumps for hotfixes between sprints.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
CIO 2026-05-07 standing rule: "are we doing a <major>.<minor>.<bug/patch> version numbering, if no, then we should switch. for the major number = 0 because we have not is a stable working version. when we do that will be V1.0.0."

**Convention**:
- Format: `V<major>.<minor>.<patch>` -- stored in `deploy/RELEASE_VERSION` `version` field
- **Major = 0** until CIO declares first stable working version. V1.0.0 will mark that milestone.
- **Minor**: bumped at every sprint close (sprint shipped + merged + deployed)
- **Patch**: bumped for hotfixes between sprints (e.g., V0.24.0 sprint close -> V0.24.1 hotfix)

**Examples in project history**:
- V0.18.0 (Sprint 18) -> V0.19.0 (Sprint 19) -> ... minor bumps each sprint
- V0.24.0 (Sprint 24 close) -> V0.24.1 (cross-module enum identity hotfix; Sprint 24 + V0.24.1 hotfix; both shipped in same calendar period)
- V0.25.0 (Sprint 25 close)

**What "stable working version" means for V1.0.0** (pending CIO confirmation; criteria proposed):
- Engine telemetry capture confirmed working across 5+ drives post-Sprint-25 ship
- B-043 PowerLossOrchestrator validated in-vehicle (post-Pi-wiring + multiple drain cycles green)
- B-047 Pi self-update validated in production (post-Sprint-26 e2e + auto-rollback drills passed)
- Sync to chi-srv-01 stable across multiple-drive batch
- Spool's tuning-analysis workflow operational (DTC retrieval + drive review + statistical baseline shelf 3-5 drives complete)

**How PM applies this rule**:
- At every sprint close, bump MINOR (V0.X.0 -> V0.X+1.0); patch stays 0 unless mid-sprint hotfix lands
- For hotfixes between sprints, bump PATCH (V0.X.0 -> V0.X.1)
- NEVER bump major from 0 without explicit CIO direction
- Document version bumps in `chore(release):` commits per `feedback_pm_sprint_close_version_bump.md`
- Validators on `deploy/RELEASE_VERSION`: `version` field must match `^V\d+\.\d+\.\d+$` regex (TD-040 / TD-044 lesson); `theme` <=50 chars; `description` <=400 chars

**Anti-pattern**: bumping minor for hotfixes (would lose the patch-vs-minor distinction). Hotfixes are PATCH not MINOR.
