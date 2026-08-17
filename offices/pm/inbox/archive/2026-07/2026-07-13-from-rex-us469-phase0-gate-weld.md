# US-469 hand-off: weld the SS-T7 run-not-trust gate into /sprint-deploy-pm Phase 0

from=Rex(Dev); to=Marcus(PM); date=2026-07-13; topic=US-469 Phase-0 gate weld (PM-owned command surface)

## What's done (in Ralph's lane, validated in-loop)

The **run-not-trust deploy-gate tripwire** is built and proven:

- **`offices/pm/scripts/deploy_preflight_gate.py`** (NEW) -- ACTUALLY RUNS
  `pytest -m "not slow"` (the suite that CONTAINS the SS-T7 systemd-parity DOA
  tripwire, `tests/pi/power/power_watch/test_systemd_parity.py`) and returns a
  PASS/HALT verdict. Structurally run-not-trust: it always invokes pytest, has
  NO marker read, NO "prior report" / "Ralph said green" flag, NO skip hatch
  (a test asserts the signature can't grow one). Non-zero pytest exit -> HALT;
  un-launchable pytest -> fail-safe ERROR (also HALT -- uncertainty never
  authorizes a deploy). CLI: `python -m offices.pm.scripts.deploy_preflight_gate --repo .`
  (exit 0 = proceed / exit 2 = HALT).
- **`tests/pm/test_deploy_preflight_gate.py`** (NEW, 12 tests, all green, ruff
  clean) -- hermetic control-flow layer + a REAL nested-pytest e2e that IS the
  validationCriterion realized: a deliberately failing test in the target suite
  makes the gate RUN pytest, observe a non-zero exit, and HALT (targets a tmp
  dir, not the project suite, so it's fast -- TD-059).

## What I need YOU to apply (PM-owned `.claude/` command surface -- Ralph is write-blocked there, lane discipline / US-467 precedent)

Add the gate as the last HALT-early step of **Phase 0** in
`.claude/commands/sprint-deploy-pm.md`. Insert AFTER the
`repair_ralph_agents.py --check` line, INSIDE the Phase-0 ```bash block:

```bash
# US-469 / SS-T7 RUN-NOT-TRUST deploy-gate tripwire (F-118). ACTUALLY RUN the
# not-slow suite -- the suite that CONTAINS the SS-T7 systemd-parity DOA tripwire
# (tests/pi/power/power_watch/test_systemd_parity.py). This is the load-bearing
# gate of Phase 0: it does NOT check a marker, does NOT trust Ralph's in-loop
# report, and does NOT best-effort-continue. It runs `pytest -m "not slow"` here
# and HALTs the deploy on any non-zero exit (exit 2). Fails SAFE (also HALT) if
# pytest cannot even launch -- uncertainty never authorizes a deploy.
python -m offices.pm.scripts.deploy_preflight_gate --repo . \
  || { echo "HALT: Phase-0 pre-flight test gate is RED (see pytest output above) -- deploy blocked."; exit 2; }
```

And add this bullet to the Phase-0 **Stop conditions** list + a row to the
**Stop-condition flowchart** (Phase 0):

> - **`deploy_preflight_gate.py` exits non-zero** (US-469 / SS-T7): the not-slow
>   suite is RED (or pytest could not launch). Hard HALT -- do NOT
>   best-effort-continue, do NOT write/trust a green marker, do NOT "we ran it
>   earlier / Ralph reported green". The gate must RUN pytest here (run-not-trust:
>   the V0.27.12 DOA lesson -- the tripwire test *existed* but the pipeline never
>   RAN it; and the V0.27.17 marker-on-failure class -- a red gate that got a
>   green marker written). Fix the red test on the sprint branch, re-run Phase 0.

Flowchart row:

| 0 | `deploy_preflight_gate.py` exits non-zero (not-slow suite RED / pytest un-launchable) | Hard HALT; fix the red test; re-run Phase 0 (run-not-trust, no marker/prior-report) |

## Verify after you apply

`bash -n`-style dry-read: Phase 0 now RUNS the gate (a real `pytest` subprocess)
and the `|| { ...; exit 2; }` HALTs the shell on non-zero -- exactly the
validationCriterion "dry-run Phase-0 with a deliberately failing test -> RUNS
pytest, gets non-zero, HALTs (not a marker / prior-report check)". The
enforcement is already proven by `test_realFailingTest_gateRunsPytestAndHalts`.

-- Rex
