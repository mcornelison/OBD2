# B-047: Pi self-update from server release registry (with deploy versioning prerequisite)

| Field      | Value                              |
|------------|------------------------------------|
| Status     | Pending PRD grooming               |
| Priority   | Medium                             |
| Filed By   | Marcus (PM), 2026-04-30 from CIO directive |
| Filed Date | 2026-04-30                         |

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
