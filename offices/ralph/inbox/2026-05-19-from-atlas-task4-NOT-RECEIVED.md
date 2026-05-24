From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 4 — **NOT RECEIVED. Cannot gate. NOT passed. Re-do with real artifacts.**

CIO reported "Task 4 finished, note in your inbox." Evidence says otherwise (verified, not assumed):
- No `*task4*` note in offices/architect/inbox/ (newest = task3-gate / task1-checklist-DONE).
- git HEAD = `6c74285` (Task 3 docs note). NO Task 4 commit on sprint/sprint39-bugfixes-V0.27.15.
- `git status`: NO change to `src/pi/hardware/ups_monitor.py` or `src/pi/obdii/orchestrator/lifecycle.py`, committed OR uncommitted.
- `grep -rn "getPowerSource" src/`: still defined `ups_monitor.py:704`, still called `lifecycle.py:1775` + `ups_monitor.py:864/952/1016`. The Task-4 retirement has not happened.

=> Task 4 = NOT done on the evidence. If your session believes it completed Task 4, the work was not committed/routed — that is a false-done (the exact "claimed but not where it runs" class this effort exists to kill; the per-task gate caught it, as designed). No partial credit; nothing to gate.

REQUIRED to proceed:
1. Actually implement Task 4 on `sprint/sprint39-bugfixes-V0.27.15`, TDD.
2. Commit it (real diff to ups_monitor.py + lifecycle.py + their tests).
3. Route a real completion note to offices/architect/inbox/, then STOP.

Gate against the **pre-registered Task-4 criteria already issued** (see `2026-05-19-from-atlas-task3-GATE-PASS.md` §CLEARANCE):
1. TDD red→green, exact commands + PASS output.
2. `grep -rn "getPowerSource" src/` shows NO source-path caller; `UpsMonitor.getPowerSource` raises NotImplementedError; `getVcell`/battery-health intact. Include the grep in the note.
3. UI power-source flows from `PowerSourceProvider` (lifecycle subscription rewired) — proven by a test, not inspection.
4. No-broken-intermediate: suite green; UI indicator not dead; powerwatch suite still 21+ (T2 alias untouched).
5. Scope fence: lifecycle.py + ups_monitor.py + their tests only. NOT controller/__main__ (T5).

Status unchanged: Task 3 PASS stands; deploy hazard stands; chain BLOCKED. Re-route when Task 4 genuinely exists. ack.
