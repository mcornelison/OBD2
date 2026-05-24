From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 6 (`ShutdownTask` Protocol + `buildV1Tasks` seam) — **GATE: PASS.** + `@runtime_checkable` ratified. Proceed to Task 7.

== independent verification (re-ran/re-read; not the note) ==
- `rg "\bPipelineTask\b" src/`: 4 hits, ALL mod-history rows or docstring rename-citations. ZERO live code uses; hard rename clean (one name per fact, no alias — consumers all updated in-commit, no T2-class hazard).
- `rg "class ShutdownTask\b" src/` -> `contract.py:48 class ShutdownTask(Protocol):` with `@runtime_checkable` decorator at :47. ✓
- `rg "def buildV1Tasks\b" src/` -> `__main__.py:114`. Body returns `[syncTask]` (V1 = exactly one task, Option A locked). Docstring carries the SINGLE-EDIT-POINT contract.
- `rg "buildV1Tasks\b" __main__.py`: `:114` def + `:173` `PW_TEST_ONESHOT` call + `:251` production `main()` call. **Both paths flow through the seam** — criterion #3 evidence by code, not inspection.
- `pytest tests/pi/power/power_watch/ -m "not slow" -q` (my run) => **23 passed** (up from 22; new seam test added).
- Scope: 6 files = `contract.py` + `pipeline.py` + `tasks/sync_with_server.py` + `__main__.py` + new `test_task_seam.py` + updated `test_contract.py`. Controller/lifecycle/provider/sensor UNTOUCHED. ✓
- Broader sweep NOT re-run for T6: the change is entirely within `power_watch/` (consumed only by the powerwatch service entrypoint); the at-risk suite (`tests/pi/power/power_watch/`) is the actual blast surface and is green. Proportionate rigor — for T4/T5 I ran broader; for an in-package Protocol rename it's corroborating, not load-bearing. Ralph reports 362 passed broader; consistent with the no-tendrils scope-fence.

== criteria — ALL MET ==
#1 TDD red→green ✓  #2 Protocol rename clean + ShutdownTask + __all__ ✓  #3 buildV1Tasks defined + production+test paths consume it + single-task ✓  #4 scope fence (6 files, settled paths untouched) ✓  #5 no-broken-intermediate (power_watch 23 green) ✓  #6 hard rename, no alias ✓.

== `@runtime_checkable` disclosure — RATIFIED on the merits ==
You correctly identified that `isinstance(t, ShutdownTask)` (the plan Step 1 test's assertion) requires `@runtime_checkable` — without it, `Protocol` `isinstance` raises `TypeError`. This is a Python language behavior the plan didn't specify; **my plan defect, owned** (small, same class as the SS-T3 `_FakePld` defect).
Architectural read: `@runtime_checkable` is a **strict superset** of the default behavior — the static structural check still works (mypy/pyright unaffected), AND consumers can verify membership at runtime by attribute-existence. For a documented plugin seam where new tasks register at runtime, that's exactly the property you want. Idiomatic Python for plugin protocols. **No downside; ratified.** Marcus FYI: the plan-of-record literal `class ShutdownTask(Protocol)` should be amended to `@runtime_checkable\nclass ShutdownTask(Protocol)` so a future re-reader doesn't reintroduce the gap.

== CLEARANCE: proceed to Task 7 — THE highest-value evidentiary gate of the chain ==
T7 = the **systemd-parity orchestration-proof test** — `tests/pi/power/power_watch/test_systemd_parity.py`. This is the structural answer to the CIO's original "is the code actually wired/running, or just written?" concern; it's the gate that would have caught V0.27.12 DOA at the source.

**Pre-registered Task-7 gate criteria (set now, before you start) — extra rigor for this one:**
1. TDD red→green, exact commands + PASS output.
2. **The test MUST spawn a real subprocess** (`subprocess.run([sys.executable, "-m", "src.pi.power.power_watch"], ...)`) — NOT an in-process `main()` call. The whole point is to exercise the import/component graph EXACTLY as systemd invokes it. An in-process call defeats the purpose.
3. **PYTHONPATH MUST match the unit's exact form**: repo root + `<repo>/src` (mirror `deploy/eclipse-powerwatch.service`). This is the V0.27.12-DOA lesson encoded as a regression net — if anyone ever simplifies PYTHONPATH or reintroduces a bare `pi.` import that bypasses one of those entries, this test loudly fails.
4. **Assertion = POSITIVE EXECUTION EVIDENCE (marker file existence)**, NOT just `returncode == 0`. Exit 0 from a no-op is not proof anything ran. A marker the chain WROTE proves the chain actually executed the (stubbed) poweroff path. Both must be asserted; marker is decisive.
5. The test uses the `PW_TEST_ONESHOT` env-var guard already in `__main__.py` (no new production code — T7 is purely a verification artifact; do NOT touch `__main__.py` to "make the test work" — if it doesn't pass against the current code, that's a defect for me to gate, not a code-change in T7).
6. Scope fence: ONLY `tests/pi/power/power_watch/test_systemd_parity.py` (new file). No production-code edits. If T7 reveals a defect, STOP and route — don't fold a fix into T7.
7. Test runs reliably on Windows (the project's primary dev platform per memory) — use `os.pathsep`, `sys.executable`, `pathlib.Path` (no shell-isms, no hardcoded `/` paths).
8. Provide the subprocess `stdout`+`stderr` capture in the assertion error message so a future failure tells the next reader WHY the chain didn't execute, not just "marker missing."

This test is the **DOA tripwire for the entire feature** — its failure is a SEV-1 signal that something has broken the wired execution path. Treat it as such.

Route the completion note + the exact `pytest test_systemd_parity.py` output (RED then GREEN) when done; STOP for the gate before Task 8.

Unchanged: deploy hazard; chain BLOCKED. ack.
