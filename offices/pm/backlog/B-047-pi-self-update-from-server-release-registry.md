# B-047: Pi self-update from server release registry (with deploy versioning prerequisite)

| Field      | Value                              |
|------------|------------------------------------|
| Status     | US-A/B/C/D shipped (Sprint 19/20/21) — code on disk + deployed; **never run end-to-end in production** (synthetic test only via US-258 Sprint 21). Sprint 26 validation pending. |
| Priority   | Medium                             |
| Filed By   | Marcus (PM), 2026-04-30 from CIO directive |
| Filed Date | 2026-04-30                         |
| Updated    | 2026-05-05 — open design Qs resolved by CIO Sprint 25 close session |
| Sprint 26  | Validation candidates filed below — production-equivalent e2e drill + automatic-rollback drill |

## Shipping status (as of 2026-05-05)

| Story  | Spec                                      | Shipped as | Sprint | Status                       |
|--------|-------------------------------------------|------------|--------|------------------------------|
| US-A   | Deploy versioning + `.deploy-version`     | US-241     | 19     | ✅ live on Pi + server        |
| US-B   | Server `GET /api/v1/version` endpoint     | US-246     | 20     | ✅ deployed                   |
| US-C   | Pi update-checker daemon                  | US-247     | 20     | ✅ deployed (untested in prod) |
| US-D   | Pi auto-update apply + rollback           | US-248     | 20     | ✅ deployed (untested in prod) |
| US-E   | Synthetic apply-path e2e drill            | US-258     | 21     | ✅ synthetic test only         |

**Honest gap**: every US- above shipped + deployed; ZERO real Pi has ever pulled a real release from the real server registry and self-applied it. Same risk class as Sprint 25 engine-telemetry regression (shipped, deployed, never validated, broke silently). Sprint 26 closes the gap with production e2e + rollback drills.

## Why

Today's deploy flow is operator-driven: CIO runs `bash deploy/deploy-pi.sh` from a Windows shell. The Pi has no autonomy to know whether it's running current code, and no way to update itself when CIO isn't at the bench. Once the car is in regular driving rotation, having the Pi auto-pull updates from a server registry on home-network reconnect / power-on means CIO doesn't need to remember which Pi is on which version, and the driving Pi stays current without manual intervention.

## Scope (4 user stories, sequenced)

### US-A (S, prerequisite — most immediate)
**Deploy versioning + timestamp.**
- Every `deploy/deploy-pi.sh` and `deploy/deploy-server.sh` run records `version + UTC date/timestamp + git commit short-hash` to a known location on the deployed tier (e.g., `/home/mcornelison/Projects/Eclipse-01/.deploy-version` on the Pi).
- Format proposal: `vSPRINT.YYYY-MM-DDTHH:MM:SSZ.GITSHORTHASH` — e.g. `v18.2026-04-29T08:29:24Z.d8583d3`. Sortable, human-readable, traceable to git.
- Server gets the same artifact at `/mnt/projects/O/OBD2v2/.deploy-version` so US-B can read from it.
- Pre-prerequisite for US-B + US-C + US-D — they all need a stable comparison key.

### US-B (M)
**Server-side "what version is current?" endpoint.**
- New endpoint `GET /api/v1/version` returns `{version, deployedAt, gitHash}` from the server's own `.deploy-version` file.
- Optional: also accept `POST /api/v1/version/check {currentVersion}` — Pi sends its own version, server returns `{updateAvailable: bool, latest: {...}, downloadUrl: ...}`.
- API_KEY-gated like other sync endpoints (US-201).
- Tests: endpoint returns parsed deploy-version content, handles missing file gracefully.

### US-C (M)
**Pi self-update trigger on home-net reconnect / power-on.**
- Wired into existing US-188 WiFi/home-network detection (`DeathStarWiFi` SSID).
- Trigger conditions: BOTH (home network seen AND `(boot just happened OR network just transitioned to home)`). NOT periodic — single-shot per event.
- Flow: Pi reads its own `.deploy-version` → queries server `/api/v1/version` → if newer version available + safety preconditions hold, runs local self-deploy.
- **Safety preconditions** for self-deploy: no active `drive_id` (engine off), `sync_log` cursor caught up to recent rows, no in-flight DTC retrieval. If any precondition fails, skip + log + retry on next eligible event.
- **Notify-vs-auto choice**: US-C v1 should AUTO-DEPLOY when safety preconditions hold. Future iteration could add a "wait for CIO confirmation" gate if auto-deploy proves risky.
- Self-deploy mechanism depends on US-D being available (server-served package); without US-D, Pi can fall back to a script that pulls the latest tarball from a known location.

### US-D (M, after C)
**Deploy pipeline pushes package to server release registry.**
- After deploy-pi.sh runs successfully, builds + pushes a tarball of the deployed tree to `chi-srv-01:/mnt/projects/O/OBD2v2-releases/<version>.tar.gz`.
- Server keeps last N releases (configurable, default 5).
- Pi's self-deploy in US-C downloads from this registry instead of relying on Windows-rsync source.
- Optional: a manifest file `releases.json` at server enumerates available versions for tooling.
- Future: a "stable channel" tag — server tracks `latest-stable` separately from `latest`, CIO promotes a stable version after validation.

## Resolved design decisions (CIO 2026-05-05 Sprint 25 grooming session)

These supersede the "Open design questions" section below. All open Qs now have a CIO-approved answer; the originals are preserved for traceability.

### D1 — Versioning scheme: SemVer (V0.X.Y)
**Resolution**: SemVer adopted in production via `deploy/RELEASE_VERSION` (e.g., `V0.24.1`). Sprint+date+hash from the original Q1 was never adopted; SemVer wins.

### D2 — Auto-deploy vs notify-and-wait: AUTO-DEPLOY when safety preconditions hold
**Resolution**: Pi auto-deploys when (a) no active drive_id (engine off), (b) sync_log cursor caught up, (c) no in-flight DTC retrieval. No CIO-confirmation gate. Confirmed CIO 2026-05-05.

### D3 — Rollback strategy: AUTO-ROLLBACK on service-won't-start (Option (b))
**Resolution**: Pi watches `eclipse-obd.service` health post-update. If the service fails to reach `active` within a configured timeout (proposal: 60 sec; CIO can set lower in Sprint 26 grooming), Pi automatically rolls back to the previous `.deploy-version` snapshot. Rationale: with no dev/prod separation (D7), automatic rollback IS the safety net for a broken release reaching production. Manual-CLI rollback (Option (a)) NOT shipped — automatic is the only viable design when there's no human in the deploy loop. Pi keeps last 3 release snapshots locally for rollback (1 current + 2 prior; configurable).

### D4 — Server release-storage cleanup: keep last 10 (default; configurable)
**Resolution**: Server keeps last 10 releases in `chi-srv-01:/mnt/projects/O/OBD2v2-releases/`. Configurable via server-side env or config. Older releases auto-pruned when count exceeds the cap.

### D5 — Authentication: API_KEY-gated (US-201 pattern)
**Resolution**: Already shipped via US-246/247. Same key Pi uses for sync.

### D6 — Network detection: re-use US-188 (DeathStarWiFi)
**Resolution**: Already shipped via US-247. No new detection logic.

### D7 — Trigger frequency + cooldown: same as DB sync trigger + 24-HOUR COOLDOWN
**Resolution** (CIO 2026-05-05): Pi update-check fires on the same triggers as DB sync (DeathStarWiFi seen + boot-just-happened OR network-just-transitioned-to-home). After EACH check completes — regardless of outcome (no-update-needed OR update-needed-and-deployed-successfully) — a **24-hour cooldown** prevents subsequent checks. Failed-check (network error / server unreachable) does NOT enter cooldown; retry on next eligible event. Per-update-attempt cooldown reset on successful check. Implementation: Pi-side timestamp persisted across reboots in a known location (e.g., `~/.cache/eclipse-obd/last-update-check.timestamp`).

### D8 — Dev/prod gating: NONE — main branch IS production
**Resolution** (CIO 2026-05-05): Every `chore(release):` commit on main automatically becomes a Pi-update candidate. No staging gate, no manual "promote to stable" step. Rationale: project has no dev/prod separation; main = prod. Risk mitigation is entirely in the **automatic-rollback** mechanism (D3) — if a bad release lands, the watchdog rolls it back within 60 sec.

### D9 — Concurrency with sync flush
**Resolution** (carried from original Q7): Self-deploy waits for sync_log cursor to be ≥ current `MAX(realtime_data.id)` before proceeding. Already in US-247 spec; preserved here.

## Sprint 26 candidate stories (production e2e + rollback validation)

### Sprint 26 candidate — Pi self-update production e2e drill (M, P1)
**Goal**: real Pi against real server, real release registry, real download + apply + restart. Mirror Sprint 25 US-286 bench-test harness pattern but for the update flow.

**Behavior**:
- Stage a synthetic-but-valid V0.X.Y release on chi-srv-01 (CIO action item to push a known-good release; in-sprint code is the validator)
- Pi update-checker daemon runs on triggered conditions (D7); detects newer version
- Pi runs full self-deploy: download tarball, validate signature/checksum, apply, restart eclipse-obd.service
- Asserts post-update: `.deploy-version` matches new version; service is `active`; no orphan from old version
- Asserts D7 cooldown timestamp written; subsequent trigger within 24h is suppressed

**Acceptance**: drive 7+ post-deploy includes a `connection_log` row with `event_type=auto_update_applied` + new `.deploy-version` content captured.

### Sprint 26 candidate — Pi auto-rollback drill (M, P1)
**Goal**: validate D3 automatic rollback on broken release.

**Behavior**:
- Stage a deliberately-broken release (e.g., syntax error in main.py) on chi-srv-01
- Pi auto-applies the broken release; eclipse-obd.service fails to reach `active` within 60 sec
- Pi automatically rolls back to previous `.deploy-version` snapshot
- Asserts post-rollback: `.deploy-version` matches the prior good version; service is `active`; rollback event logged

**Acceptance**: synthetic broken-release drill triggers rollback; production-Pi state recovers; alarm event written for CIO post-mortem.

### Sprint 26 candidate — Cooldown timestamp persistence (S, P2)
**Goal**: D7 cooldown survives reboots.

**Behavior**: Persist last-check timestamp at `~/.cache/eclipse-obd/last-update-check.timestamp`. Pi reads on boot; respects cooldown across power cycles.

**Acceptance**: synthetic test simulates reboot mid-cooldown; verifies cooldown is honored.

### Sprint 26 candidate — Server release-registry retention (S, P2)
**Goal**: D4 keep-last-10 policy.

**Behavior**: After each new release lands in `OBD2v2-releases/`, server prunes oldest releases beyond config-configured retention (default 10). Logged.

**Acceptance**: synthetic test simulates 12 releases; verifies oldest 2 pruned.

## Open design questions (for PRD grooming)

1. **Versioning scheme**: Sprint+date+hash proposed above (`v18.2026-04-29T08:29:24Z.d8583d3`). Other options: SemVer (`v1.18.0`), date-only (`2026-04-29`), commit-hash-only (`d8583d3`). Sprint+date+hash is most informative + sortable; no tooling currently consumes structured version data so any scheme works. Recommend the verbose one.

2. **Auto-deploy vs notify-and-wait**: US-C v1 auto-deploys when safety preconditions hold. Risk: a bad release lands on Pi during a quiet window, breaks something. Mitigation: stable-channel separation (US-D extension). Revisit after first auto-update event.

3. **Rollback**: If new version breaks Pi, how does it recover? Options: (a) Keep N previous versions on Pi disk, manual rollback CLI; (b) Pi watches eclipse-obd.service health post-update + auto-rolls back if service won't start within X seconds. (b) is safer but more complex. Defer to PRD.

4. **Server release-storage cleanup**: Last 5 releases? 10? Forever? Default 10 with config knob.

5. **Authentication**: API_KEY-gated (matches US-201 pattern). Re-use the same key Pi has for sync.

6. **Network detection re-use**: US-188 already detects `DeathStarWiFi`. US-C wires into that signal — no new detection logic needed.

7. **Concurrency**: Self-update during active drive must NOT happen. Safety precondition check covers this. But what if Pi is mid-sync-flush when an update lands? Self-deploy should wait for sync_log cursor to be ≥ current `MAX(realtime_data.id)` before proceeding.

## Operator-action gates (action items, NOT sprint stories per Sprint 18 rule)

- CIO blesses a release as "stable" before stable-channel pulls trigger (if stable-channel ships in US-D extension)
- CIO sets up `~/OBD2v2-releases/` directory on chi-srv-01 with mcornelison ownership (one-time)
- CIO accepts the auto-update behavior on first activation (or directs notify-and-wait instead)

## Sprint sizing

- US-A (versioning) — S, ready for Sprint 19 inclusion as prerequisite for everything else
- US-B (server endpoint) — M, depends on US-A
- US-C (Pi self-update) — M, depends on US-B
- US-D (release registry) — M, depends on US-A, parallels US-C

Whole feature: ~13 points across 4 stories. Could span Sprint 19 + Sprint 20 (US-A in 19, others in 20).

## Related

- US-188 (WiFi / DeathStarWiFi home-network detection) — Sprint 13 building block, US-C consumes
- US-201 (B-044 API_KEY deploy-time bake-in) — Sprint 14, sets the auth pattern US-B reuses
- US-213 (TD-029 server migration gate) — Sprint 16, parallel "deploy automatically applies migrations" pattern
- US-226 (Pi → server sync) — Sprint 18, set the pattern for Pi-initiated network ops
