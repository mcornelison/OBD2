from=Marcus(PM); to=Rex(Dev); date=2026-07-02; topic=DISPATCH Sprint 53/V0.29.7 -- analytics foundation + ops/power hygiene (bench-only, 10 stories); audience=agent; urgency=high; refs=US-431,US-432,US-433,US-434,US-435,US-436,US-437,US-438,US-439,US-440

# Marcus -> Rex: Sprint 53 / V0.29.7 DISPATCHED

Branch **`sprint/sprint53-V0.29.7`** forked from `dev`, pushed, upstream set; checkout is on it. **10 stories.** Atlas-reviewed (no BLOCK). Several are **VERIFY-FIRST** — read carefully before writing code.

## Testing discipline (your contract was fixed — `prompt.md` 561e35a)
Run the story's **TARGETED tests SYNCHRONOUSLY** (foreground, read the summary line) and **commit within the iteration**. Do NOT run the full `pytest tests/` suite in-loop, do NOT background a test to "wait for the result" (TD-059 — it stalled you twice; it's fixed now, keep it fixed).

## Suggested order (mostly independent)
**Fast verify-first closes first:**
1. **US-433 PowerMonitor->power_log (likely DONE)** -- Atlas: `lifecycle.py:1873` US-243 path active + US-412 synced. Re-query the live Pi; if populating, **close-with-evidence (row counts + timestamps), NO code.**
2. **US-434 drain_event close (likely MOOT)** -- Atlas: `startDrainEvent`/`endDrainEvent` have **0 production callers**. Confirm + no stuck-open rows -> **close as moot with evidence.** Do NOT build an open-path (contradicts the retired ladder) -- flag me first if you somehow find one.

**Substantive:**
3. **US-431 MAX17048 SOC% calibration** -- protocol + script; feeds the US-427 cold-start threshold with real data. UPS-drain rig.
4. **US-432 drive_detect idle-poll (VERIFY-FIRST + A-9 GUARDRAILS)** -- US-242/B-049 ALREADY built idle->active escalation; root-cause the **RESIDUAL** gap only. **Guardrails:** (a) must NOT regress US-388 close-guarantee (`evaluateTimeouts`) or the `drive_id` NULL-latch; (b) note it for the A-9 IRL re-gate. This is the A-9 start-side -- tread carefully.
5. **US-435 hostname cleanup** -- sweep stale refs -> canonical (Pi now `Chi-Eclips-01`); don't break deploy/SSH.
6. **US-436 derived signals (SERVER-SIDE)** -- accel + est. distance from speed+time, in `src/server/analytics/` per-drive (Atlas-confirmed B-104: server is sole analytics writer; NOT Pi). Guard zero-dt/gaps.
7. **US-437 tester bug rollup** -- the **8 BUGS** from Argus's V0.28+ data-profile findings (design items OUT). Per-bug verify-first (some may be fixed); fix-with-test or close-with-evidence.
8. **US-438 cross-drive tool (SERVER-SIDE)** -- compares metrics across drives (incl. US-436 derived signals); excludes `data_source!='real'` (F-116 -- drive 33 out). Reads `obd2db`.
9. **US-439 commented-deps** -- restore/remove/document each; import smoke.

**Last:**
10. **US-440 doc-sync + backlog archival** -- architecture.md + regression_manifest; **archive F-007/F-052/F-100 + US-422/423** (superseded).

## Validation = BENCH ONLY
Unit/fixture, DB introspection, live-Pi re-query (verify-first), UPS-drain rig. Several stories are analysis/CLI (bench-verifiable). NO drive drills.

## Notes
- Commit to THIS branch; stale index.lock = TD-057 (wait/retry, never force).
- US-436/438 server-side, US-432 A-9-guarded -- these have Atlas's design conditions baked into the ACs; honor them.

CIO launches `ralph.sh` from his shell.

-- Marcus
