# Phase-2 Shutdown Sequencer — IRL Acceptance Runsheet

- **Date:** 2026-05-19 (rewritten to spec §10 acceptance gate sequence; SS-T10).
- **Branch:** `sprint/sprint39-bugfixes-V0.27.15` (Shutdown Sequencer T1–T9 all GATE-PASS by Atlas; runsheet is the last in-code task before the sprint hands off to the CIO bench).
- **Who runs this:** CIO (Ralph does not deploy or drive Pi/IRL actions).
- **Goal:** prove the integrated ShutdownSequencer end-to-end: GPIO6 ground-truth power-loss (via `PowerSourceProvider`) → 5 s smoothing + boot-grace + arm-self-check → bounded best-effort `SyncWithServerTask` (or benign skip) → graceful `systemctl poweroff` → **unattended auto-boot** on power return — **5 consecutive clean cycles**.

> **This runsheet operates on the POST-REDEPLOY Pi.** The current Pi
> (`chi-eclipse-01`) runs the deployed V0.27.14 (`0125417`) code with the
> `eclipse-powerwatch` service *manually removed* (post-bricking recovery,
> see §6). Marcus owns the redeploy decision and timing
> (`/sprint-deploy-pm`); the deploy hazard stands until this drill passes.

## 0. Atlas sign-off lineage (already complete — recorded as baseline)

| Gate | Status | Atlas note |
|---|---|---|
| SS-T1 regression-first + bench checklist | PASS | `2026-05-18-from-atlas-task1-GATE-PASS.md` |
| Bench Check A (GPIO6 PLD line) | PASS — hi×5→lo×4→hi×5→lo×7→hi×6→lo×4, clean bidirectional toggle; `pldPowerPresentHigh=true` correct on this unit | `2026-05-18-from-atlas-checkA-GATE-PASS.md` |
| Bench Check B (`POWER_OFF_ON_HALT=1` unattended wake) | PASS — 1 cycle (Finding B empirically cleared; full 5-cycle gate = this drill) | `2026-05-18-from-atlas-checkB-GATE-PASS-finding-b-cleared.md` |
| SS-T2..T9 (config / SSOT module / SSOT enforcement / Sequencer / Protocol seam / orchestration-proof / EEPROM defect / spec reconciliation) | ALL PASS | `2026-05-19-from-atlas-task[2-9]*.md` |

**Chain unblock is now gated only on this runsheet + the IRL drill itself.**
This is the **last in-code task** before the sprint hands off to the CIO bench.

---

## 1. Preconditions — verify before kicking off the drill

- [ ] **Battery charged.** UPS LiPo charged on external power, Pi idle, for ≥1 h before starting. Long benches of forced cycles drain the pack flat (a near-empty pack will trip the `vcellFloorVolts=3.50` emergency short-circuit mid-cycle and confuse the drill).
- [ ] **`chi-eclipse-01` reachable on home WiFi**; `chi-srv-01` (10.27.27.10) up (for the reachable-path leg in §3).
- [ ] **EEPROM is `POWER_OFF_ON_HALT=1`** on the Pi (one-liner): `ssh chi-eclipse-01 "sudo rpi-eeprom-config | grep POWER_OFF_ON_HALT"` → expect `POWER_OFF_ON_HALT=1`. (If absent or `=0`, the post-redeploy enforce script will set it on the next deploy; verify before §2.)
- [ ] **`eclipse-powerwatch` reinstalled by the latest deploy.** It was manually removed during the V0.27.14 bricking recovery; `deploy/deploy-pi.sh` reinstalls it via `step_install_power_watch_unit`. Confirm: `ssh chi-eclipse-01 "systemctl is-enabled eclipse-powerwatch.service"` → expect `enabled`.
- [ ] **Service active and armed.** `ssh chi-eclipse-01 "systemctl is-active eclipse-powerwatch.service && journalctl -u eclipse-powerwatch.service -b --no-pager | tail -10"` → expect `active`, and the startup line `powerwatch service up (GPIO%d PLD SSOT trigger): perTask=20s totalCap=45s vcellFloor=3.50V smoothing=5s bootGrace=120s` (config-tunable; the bootGrace + smoothing values come from `pi.powerWatch.{bootGraceSec,smoothingSec}`).
- [ ] **No DOA marker in the journal.** `ssh chi-eclipse-01 "journalctl -u eclipse-powerwatch.service -b --no-pager | grep -E \"No module named|Traceback|arm self-check FAILED\""` → expect **no output**. (`arm self-check FAILED` means GPIO6 didn't read power-present at start — the sequencer correctly refuses to arm; investigate before the drill.)

---

## 2. STAYS-UP precondition (the regression net the bricking loop violated)

Before any battery cycle: **prove the Pi stays up on external power past the
arm + smoothing window without self-powering-off.** The 2026-05-18 bricking
loop self-shutdown ~10–15 s after boot every time; if that recurs, the drill
cannot start and the gate has caught a regression.

Run **N consecutive clean boots on external power** (CIO ratifies N — Atlas
suggests N=3 as the minimum; CIO may raise it). For each boot:

```bash
# from the dev box
ssh chi-eclipse-01 "sudo reboot"
# wait ~90s for the Pi to boot, then:
ssh chi-eclipse-01 "uptime && systemctl is-active eclipse-powerwatch.service && \
  journalctl -u eclipse-powerwatch.service --since='-5 min' --no-pager | tail -20"
```

Pass criteria for the stays-up precondition:
- [ ] Each boot: Pi stays up **strictly longer than `bootGraceSec + smoothingSec`** (default 120 + 5 = 125 s); `eclipse-powerwatch.service` reads `active`; the service does NOT log `entering bounded pre-shutdown window` or `graceful poweroff` on external power.
- [ ] Across N boots: zero self-shutdowns. If any boot self-powers-off, **STOP**, file the journal output, route to Atlas — that is a regression of the bricking class (T7's DOA tripwire passing in CI does not prove anything about boot-time GPIO transient behavior).

---

## 3. On-battery cycles — Cycle A (full graceful loop) + Cycle B (mid-window abort)

Tail the watcher in one terminal during every cycle:

```bash
ssh chi-eclipse-01 "journalctl -u eclipse-powerwatch.service -f"
```

### Cycle A — full graceful loop

1. Pi on external (car/wall) power; `eclipse-powerwatch` active and armed; `chi-srv-01` reachable.
2. **Remove external power** (key off / unplug). `PowerSourceProvider` reports power LOST → 5 s smoothing → bounded pre-shutdown window opens.
3. Verify the journal sequence on the running tail:
   - `GPIO%d PLD => external power LOST -- entering bounded pre-shutdown window`
   - reachability: **reachable** → `SyncClient.forcePush` runs (`SyncWithServerTask`); **unreachable** → `chi-srv-01 unreachable -- benign skip`. Either resolves the window (success / benign / failed-after-retry — never hangs past `totalCapSec=45s`).
   - `pre-shutdown window resolved -- graceful poweroff` → `systemctl poweroff`.
4. Pi goes fully dark. Confirm: `ping chi-eclipse-01` stops; SSH disconnects.
5. **Restore external power** (key on / ACC / plug). With `POWER_OFF_ON_HALT=1` + the X1209 HAT, the PMIC sees a real power-cycle edge → **Pi auto-boots unattended, zero human touch**.
6. Pi boots; confirm `eclipse-obd` and `eclipse-powerwatch` both `active` again:
   ```bash
   ssh chi-eclipse-01 "systemctl is-active eclipse-obd.service eclipse-powerwatch.service && uptime"
   ```

### Cycle B — power-return abort (smoothing + window safety, run ≥1)

1. Same as A steps 1–2 (induce sustained-lost).
2. **Restore power BEFORE the smoothing window closes** (within `smoothingSec=5s` of unplug). The sequencer aborts before any window opens.
3. Verify (the tail): `power-lost NOT sustained through 5s smoothing window -- transient (external power present), abort + resume`. The Pi **does NOT power off**.
4. Also run the in-window variant ≥1×: restore power AFTER the window opens (but before `totalCapSec`). Verify: `power returned during window -- abort, resume normal op`. Pi stays up.

### Per-cycle checks (every cycle)

- [ ] No `No module named` / `Traceback` in the eclipse-powerwatch journal for the cycle. (T7's DOA tripwire test should never let this happen at deploy-time, but verify on real hardware anyway.)
- [ ] No `arm self-check FAILED` mid-cycle. (Means GPIO6 read failure during the boot-grace loop — investigate.)
- [ ] If a sync fault occurred: a typed outcome record exists.
  ```bash
  ssh chi-eclipse-01 "cat /home/mcornelison/Projects/Eclipse-01/data/powerwatch_outcome.json"
  ```
  Expect one of `{ok, server_unavailable, sync_failed_after_retry, real_error}` — never absent on a window that ran the sync task. Producer-only; a consumer is out of scope by design.
- [ ] Spool read-only re-verify: `power_log` / sync state / data integrity unchanged by the cycle (no tuning edits — Spool SME read-only).

---

## 4. Acceptance gate (Phase-2 closes when ALL hold)

- [ ] **5 consecutive clean Cycle-A loops** (CIO-ratified count per spec §10: **5 consecutive**, not "≥3" — the bar). Sequence per loop: external-power → unplug → sustained lost (5 s smoothed) → window runs (sync reachable or benign skip) → graceful poweroff → **unattended auto-boot, zero human touch** → service active again.
- [ ] **≥1 clean Cycle-B** (smoothing-blip variant): power restored within `smoothingSec` → abort, no window, no poweroff.
- [ ] **≥1 clean Cycle-B** (mid-window variant): power restored after window open but before `totalCapSec` → abort, resume, no poweroff.
- [ ] **Zero DOA-class journal errors** across all 5+ cycles (no `No module named`, no `Traceback`).
- [ ] **Zero unprovoked self-shutdowns** outside the drill (the bricking-class signal).
- [ ] Spool read-only sign-off (data integrity intact across the drill).
- [ ] **Sign-off note:** drill ran on the SS-T2-validated interim bounds (`smoothingSec=5`, `bootGraceSec=120`, `totalWindowCapSec=45`, `vcellFloorVolts=3.50`, `perTaskTimeoutSec=20`, `poweroffTimeoutSec=30`, `uiPollSec=2`). Spool to confirm from real battery-runtime data whether any bound should be tuned before declaring Phase-2 *fully* accepted (config-only change, no code — commit `d7849ce` tracks this).

---

## 5. Explicit scope (what this does NOT test — by design)

- **The retired VCELL-heuristic source path.** SS-T4 removed it; `UpsMonitor.getPowerSource()` is a `NotImplementedError` tripwire with zero callers. There's nothing to drill there.
- **Phase-3** (Bluetooth/OBD reconnect on car/wall power): later, not in this acceptance.
- **Boot-progress instrument `CLEAN_COMPLETE`** (Finding A): demoted to last-priority housekeeping; not gating Phase-2.
- **Deferred housekeeping (non-blocking, flagged):** out-of-scope stale references in `core.py:209/453`, `test_power_monitor_db_write.py:112`, `architecture.md:172/417` (post-T9 doc-hygiene); the `drain_forensics` tool + `drain-forensics.service` are vestigial (only scraped the deleted ladder's journald telemetry); `SHUTDOWN_SUCCESS_MARKER` log string + ~15 docstrings carry stale `PowerDownOrchestrator` prose; TD-054 ShutdownHandler dead source-reaction wiring. Zero functional impact; separate one-pass cleanup when convenient.

---

## 6. Recovery procedure — if `eclipse-powerwatch` misbehaves

> Lesson from the 2026-05-18 bricking incident:
> **`systemctl mask` does NOT work for this service** — `deploy-pi.sh`
> installs a real unit file at `/etc/systemd/system/eclipse-powerwatch.service`,
> which `mask` cannot override. The correct recovery is stop/disable/rm.

If any cycle self-powers-off unexpectedly, or the bricking-class loop
recurs (Pi self-shuts ~10–15 s after every boot even on external power):

```bash
# All ONE LINE each — paste-safe (no fragile multi-line heredocs)
ssh chi-eclipse-01 "sudo systemctl stop eclipse-powerwatch"
ssh chi-eclipse-01 "sudo systemctl disable eclipse-powerwatch"
ssh chi-eclipse-01 "sudo rm -f /etc/systemd/system/eclipse-powerwatch.service /etc/systemd/system/multi-user.target.wants/eclipse-powerwatch.service"
ssh chi-eclipse-01 "sudo systemctl daemon-reload"
ssh chi-eclipse-01 "systemctl status eclipse-powerwatch.service"   # expect "could not be found"
```

After recovery: `eclipse-obd` stays healthy (independent service, separate
failure domain by design — spec §7). The Pi remains a normal OBD collector
without the shutdown sequencer. To re-engage, re-run `deploy/deploy-pi.sh`
(reinstalls + re-enables via `step_install_power_watch_unit`). **Do not
redeploy on faith** — re-run §1 preconditions and §2 stays-up precondition
before any new cycles.

The arm-self-check (refuses to arm if GPIO6 doesn't read power-present at
start; SS-T3/T5) is the second safety net: a wrong redeploy disarms the
sequencer rather than re-bricking. Combined with the recovery above, the
worst-case outcome of any redeploy is "shutdown sequencer inert" — not "Pi
bricks itself." But verify, don't assume.
