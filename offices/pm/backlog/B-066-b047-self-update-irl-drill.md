# B-066: B-047 self-update IRL drill (validate F-013 + F-014 with V0.27.X test payload)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P1) -- gates V0.27 chain merge to main per chain-end-merge rule |
| Status       | Pending (V0.27.5+ candidate; gates the eventual chain merge) |
| Category     | infrastructure / testing |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | V0.27.4 must complete first (no in-flight bug fixes during the drill) |
| Created      | 2026-05-10             |

## Description

Per CIO 2026-05-10 chain-end-merge rule: main = "fully functional working system." When the V0.27 chain (V0.27.1 + V0.27.2 + V0.27.3 + V0.27.4 + ...) merges to main, the resulting state should be production-validated end-to-end.

**F-013 (Pi self-update applies cleanly) and F-014 (auto-rollback on broken release)** are both `lastValidated=null` in `regression_manifest.json` -- synthetic tests only (US-258 + US-293 + US-294 from Sprint 19/21/26), never IRL drilled.

If the V0.27 chain merges to main without F-013/F-014 IRL validation, main carries unvalidated features. That violates the "fully functional working system" bar for main.

**B-066 = pre-merge gate**: drill F-013 + F-014 IRL before chain-merge so main = actually-validated stable.

## Drill Protocol (proposed)

### Phase 1 — F-013 self-update applies cleanly

1. Pi running on V0.27.X-N (some intermediate V0.27 chain version, NOT the latest)
2. Server release registry has V0.27.X (latest chain tip) staged as available release
3. Wait for Pi to detect available update (B-047 update-checker daemon, every N minutes)
4. Verify Pi enters update-apply path (engine-off + sync-caught-up + no-DTC preconditions per Sprint 26 US-295)
5. Pi downloads V0.27.X release; applies; restarts service
6. Verify Pi `.deploy-version` post-restart shows V0.27.X (not V0.27.X-N)
7. Verify service active + healthy post-update

**Acceptance**: F-013 lastValidated bumped to drill date; bumping evidence: B-047 self-update completed CIO-observed without manual intervention.

### Phase 2 — F-014 auto-rollback on broken release

1. Pi running on V0.27.X (just-applied via Phase 1)
2. Stage a deliberately-broken V0.27.X+1 release on server (e.g., service that fails to start within 60s)
3. Wait for Pi to detect, download, apply
4. Service-fails-to-start within 60s; auto-rollback path triggers (Sprint 26 US-294)
5. Verify Pi rolls back to V0.27.X cleanly
6. Verify service active on V0.27.X post-rollback

**Acceptance**: F-014 lastValidated bumped to drill date; bumping evidence: deliberately-broken release rolled back without manual intervention; Pi service stays healthy on V0.27.X.

## Acceptance Criteria

- [ ] B-066 drill protocol documented in `offices/pm/scripts/` (or equivalent runbook location)
- [ ] CIO runs Phase 1 + Phase 2 IRL (Pi on bench wall power; server staging via deploy-server.sh + manual release-registry stage)
- [ ] F-013 lastValidated + validatedBy bumped in regression_manifest.json
- [ ] F-014 lastValidated + validatedBy bumped in regression_manifest.json
- [ ] Drill summary filed as PM note documenting evidence + any gotchas surfaced

## Validation Script Requirements

- **Input**: Pi running on intermediate V0.27.X-N; server release registry has V0.27.X-tip
- **Expected Output (Phase 1)**: Pi auto-pulls + applies V0.27.X; `.deploy-version` reflects new version; service active
- **Expected Output (Phase 2)**: deliberately-broken V0.27.X+1 triggers rollback; Pi stays on V0.27.X
- **Database State**: `connection_log` should record `auto_update_applied` event for Phase 1 + `auto_update_rolled_back` for Phase 2 (per US-247/248/258 schema)
- **Test Program**: drill runbook + observation; no automation needed -- this is a CIO-attended IRL test

## Why This Story Matters Now

The chain-end-merge rule means main waits for whole V0.27 chain to be fully functional working. F-013 + F-014 are PART of the V0.27 stack (B-047 work shipped Sprint 19-21 + Sprint 26). Untested IRL means we don't know if they actually work.

If we merge V0.27 to main without B-066 drill, the FIRST IRL test of B-047 self-update will be on production main -- a strictly worse blast radius. Better to drill on a V0.27.X intermediate chain version where rollback is local.

## Notes

**B-063 hardware blocker NOT a prerequisite for B-066** -- self-update drills run with Pi on bench wall power. Engine-on doesn't need to happen.

**Cross-reference Sprint 27 close session note** (2026-05-09): "After Sprint 28 validates and merges to main as V0.27.2, file B-063 for V0.27.3+: 'B-047 self-update IRL drill: validate F-013 + F-014 with V0.27.X as controlled test payload.' That gives B-047 its own validation moment with rollback procedure documented." -- B-066 is the realization of that note, just numbered differently.

**Sprint timing**: file as V0.27.5+ candidate. Should ship BEFORE V0.27 chain-merge to main. Could also be the LAST V0.27 sprint before chain merges -- "V0.27.5 = drill the chain validates end-to-end, then merge."

## Source

- `regression_manifest.json` F-013 + F-014 entries (lastValidated=null since file creation)
- Sprint 26 close: B-047 production e2e drill (US-293/294/295/296/297) shipped synthetic tests; never IRL drilled
- Sprint 27 close session note (Marcus PM 2026-05-09)
- CIO 2026-05-10 chain-end-merge rule + open V0.27.4 grooming session question "any gaps you have + want to research?" -> Marcus surfaced this
