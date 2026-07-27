# PM Action Items

Operational follow-ups gated on sprint code shipping. **Not** sprint stories, **not** TDs, **not** issues — these are tasks owned by Marcus (PM) or by humans (CIO, Spool) that fall outside the dev-only sprint scope per `feedback_sprint_scope_dev_only.md`.

Format per item:
- **AI-NNN** Title — Owner — Status — Filed date — Source

---

## Open

### AI-001 Phantom-path drift in `sprint.json scope.filesToTouch` — fix Marcus-side template generator
- **Owner**: Marcus (PM)
- **Status**: open
- **Filed**: 2026-05-01
- **Source**: Spool sprint22-drain-forensics-spec Story 7 + 8-session pattern noted in MEMORY.md "Small open items"

**Pattern**: Across Sprints 14-21 (8 sessions), Ralph has surfaced ~1 phantom path per sprint in `sprint.json` story scope.filesToTouch — paths that don't exist in the current repo state at sprint-load time. Recent example: Sprint 21 US-252 listed `src/pi/data/database_schema.py` but actual path is `src/pi/obdii/database_schema.py` (Pi schema lives at `obdii/`, not `data/`). Ralph wastes audit-time tracking down the real path on every occurrence.

**Why this is a PM action item, not a sprint story**: This is template-generator work on the PM side (Marcus's grooming workflow), not Ralph dev/code work. Per Sprint 19+ dev-only sprint scope rule, it cannot live in `sprint.json`.

**Proposed remediation**:
1. Add a pre-flight check to `offices/pm/scripts/sprint_lint.py` that walks every story's `scope.filesToTouch`, strips any parenthetical commentary, and verifies the path exists in the current repo state. NEW files (annotated `(NEW ...)`) are exempt — only UPDATE-paths get the existence check.
2. Run lint at story-add time AND before commit. Document the workflow in `offices/pm/projectManager.md` PM Rules.
3. Optional follow-up: when grooming a new story, batch-grep the proposed paths via `Glob` before writing the contract.

**Acceptance** (Marcus self-checks):
- `sprint_lint.py` flags non-existent UPDATE paths as `error` (not warning) on the next sprint contract.
- Run on Sprint 22 contract and confirm zero phantom paths (current state).
- Schedule the lint addition for next PM session (not Sprint 22 — out of dev scope).

---

### AI-003 Rename the Pi OS hostname `Chi-Eclips-Tuner` → `chi-eclipse-01` (unblocks US-473)
- **Owner**: CIO (Mike)
- **Status**: open
- **Filed**: 2026-07-15
- **Source**: Session 55 grooming; B-102/F-102 (code-resolution sweep US-435 shipped V0.29.7; the actual host rename remains)

**What**: On the Pi, run `sudo hostnamectl set-hostname chi-eclipse-01` (and update `/etc/hosts` if it pins the old name), then reboot/verify. This is an **ops action on the live Pi** — it needs the Pi powered + SSH, so per the dev-only sprint-scope rule it can't be a Ralph story.

**Why it matters**: **US-473** (the code/config/docs/SSH convergence sweep, F-102) is BLOCKED on this — Ralph must not sweep every reference to `chi-eclipse-01` while the host still answers to `Chi-Eclips-Tuner` (would break deploy-pi.sh + SSH). Sequence is: (1) CIO renames the host → (2) US-473 sweeps the code to match → (3) F-102/B-102 closes.

**Acceptance**: `ssh chi-eclipse-01 hostname` returns `chi-eclipse-01`; then US-473 can dispatch. If the CIO does this in the V0.29.13 sprint window, US-473 rides that sprint; otherwise US-473 slips to the next sprint.

---

### AI-004 🔴 REVERT the Pi's OBD MAC from the phantom `…3C…` back to `00:04:3E:85:0D:FB` (likely the connection fix)
- **Owner**: CIO (Mike) — ops on the Pi (2-minute fix; likely restores the connection)
- **Status**: open — **HIGHEST PRIORITY (the true gate)**
- **Filed**: 2026-07-20
- **Source**: BT-connection archaeology 2026-07-20 + CIO's paired-phone photo (ground truth `OBDLink LX` / `00:04:3E:85:0D:FB`)

**What / why**: On 2026-07-17 the architect repointed the Pi's live `/etc/default/obdlink` + `.env` to a **phantom MAC `00:04:3C:84:15:6B`** (a mis-identified stranger's device — a BT MAC is burned in and cannot change on factory reset). If that's still on the Pi, `rfcomm bind` targets a device that doesn't exist → no `/dev/rfcomm0` → **no connection → zero capture**. This is the most likely reason a weekend of drives captured nothing.

**Steps** (backups already on the Pi):
1. `ssh <pi> "grep OBD_BT_MAC /etc/default/obdlink /home/mcornelison/.../.env"` — confirm whether it says `…3C…`.
2. If phantom: restore the backups `/etc/default/obdlink.bak-20260717` + `.env.bak-pre-macfix-20260717`, OR set `OBD_BT_MAC=00:04:3E:85:0D:FB` in both.
3. `sudo systemctl restart rfcomm-bind.service` (or reboot) → `rfcomm show` should bind `/dev/rfcomm0` to `…3E…`.
4. Verify: `bash scripts/verify_bt_pair.sh` then `bash scripts/verify_live_idle.sh` (engine idling) → expect CAPTURE PASS.

**Acceptance**: the Pi's `/etc/default/obdlink` holds `00:04:3E:85:0D:FB`; `verify_live_idle.sh` passes (realtime_data rows landing). Then the true gate (Pi online + connecting + capturing) is met and an IRL drive is worth doing. US-477 (V0.29.14) makes the deploy self-heal this so it can't recur.

---

### AI-005 Wire the genuine Adafruit ICM-20948 #4554 to the Pi I2C bus (@0x69) -- unblocks US-478
- **Owner**: CIO (Mike) -- hardware install on the Pi
- **Status**: open
- **Filed**: 2026-07-27
- **Source**: Session 55 UI-foundation grooming; genuine IMU received 2026-07-27 (replaces the dead clones)

**What**: The genuine ICM-20948 #4554 arrived but is **not yet on the Pi's I2C bus** -- `i2cdetect -y 1` (2026-07-27) shows only `0x29` (light) + `0x36` (UPS), no `0x69`. Wire/mount the board to the Pi's I2C (SDA/SCL/3V3/GND, same seat as the dead clone) so it enumerates at `0x69`.

**Why it matters**: **US-478** (IMU bring-up) can have its enable+bridge CODE written, but its read-validation (accel/gyro/mag live @0x69) **cannot pass until the board is on the bus**. The IMU data path is also the prerequisite for the **live driving cards** (W-11 home card) -- Iris's design + Ralph's build both need real IMU data to validate. So this wiring gates the whole live-motion UI line.

**Acceptance**: `ssh <pi> "sudo i2cdetect -y 1"` shows `69`; then US-478 can validate. (The `adafruit-circuitpython-icm20x` driver is already installed.)

---

## Closed

### AI-002 Ralph commit-but-not-stage detector — sprint_lint commit-vs-claim verifier
- **Owner**: Ralph (via Sprint 24 US-282)
- **Status**: Resolved (2026-05-03, Sprint 24 US-282, Rex Session 155)
- **Filed**: 2026-05-03
- **Source**: Sprint 22 US-262 rescue commit `096dade` + Sprint 23 US-275/276/277 rescue commit `6d8af99`

**Pattern**: Twice in two sprints, Ralph's per-story `feat:` commits LOG the work in commit messages + populate `sprint.json feedback.filesActuallyTouched` lists, but the actual src/test/deploy file changes only land in working tree (never staged). Sprint-close merge brings empty story commits to main; PM catches it via post-merge `git status`; rescue commit recovers the work. PM-side detection cost is high — only caught at sprint close by accident.

**Remediation** (shipped Sprint 24 US-282): extended `offices/pm/scripts/sprint_lint.py` with `lintFeedbackVsTreeDiff(story, repoRoot, sprintBaseRef)` function + `_collectChangedFilesSinceRef` + `_resolveSprintBaseRef` helpers + `--check-feedback` CLI flag (OPT-IN). For each story with populated `feedback.filesActuallyTouched`, walks `git log <merge-base HEAD main>..HEAD` and asserts every claimed path (parenthetical-stripped via existing `parseFilesToTouchEntry` helper) appears in at least one commit's tree-diff. Emits `feedback claim missing from commits: '<path>'` per missing path. Default off so pre-ship lint runs (empty feedback by design) do not spurious-fail.

**First-catch in same sprint**: Running `--check-feedback` against current Sprint 24 sprint.json caught **US-280's** claim of `tests/pi/power/test_orchestrator_state_file.py` — file exists on disk (working-tree modification) but is not in any commit between sprint base (`cd8088c`) and HEAD. **Third occurrence of the bug-class in three consecutive sprints** (Sprint 22 US-262 → rescue `096dade`; Sprint 23 US-275/276/277 → rescue `6d8af99`; Sprint 24 US-280 → caught by US-282 in same sprint). PM/CIO action: retroactive ship-commit pattern (similar shape to `096dade` and `6d8af99`) before sprint-close merge to bring US-280's working-tree changes onto the sprint branch. The catch IS the durable-fix's proof-of-concept — first sprint with the check prevented the bug from reaching main silently.

---
