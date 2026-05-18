# Phase-2 Power-Watch — Deploy + IRL Acceptance Runsheet

- **Date:** 2026-05-18
- **Branch:** `sprint/sprint38-bugfixes-V0.27.12` (Phase-2 T1–T9 code-complete, full not-slow pi suite green: 1545 passed / 0 fail; eclipse-powerwatch + T8 real-invocation guard green).
- **Who runs this:** CIO (Ralph does not deploy or drive Pi/IRL actions).
- **Goal:** prove the CIO "when" end-to-end: sustained-on-battery → bounded best-effort server-sync (or benign skip) → graceful poweroff → **unattended auto-boot** when power returns.

---

## 0. Preconditions (verify before deploying)

- [ ] **Phase-1 (unattended wake) is GREEN.** EEPROM-first fix already validated 3/3 IRL (latest bootloader + `POWER_OFF_ON_HALT=1` + `WAKE_ON_GPIO=1`, Geekworm X1209, car-power topology). Phase-2 acceptance *builds on this* — if the Pi no longer auto-boots after a clean `systemctl poweroff`, stop and re-fix Phase-1 first; Phase-2 cannot pass without it.
- [ ] Pi `chi-eclipse-01` (10.27.27.28) reachable on home WiFi; server `chi-srv-01` (10.27.27.10) up (for the reachable-path leg).
- [ ] Working tree on the sprint branch; Phase-2 commits present (`git log --oneline | grep power_watch` shows T1–T9 + the T9 cutover `9adb0fb`).
- [ ] **Interim bounds note:** ships with conservative-interim `pi.powerWatch.*` (perTask=20s, totalWindowCap=45s, vcellFloor=3.50V, poweroff=30s). These are bounded+safe — the drill runs correctly on them. Spool battery-runtime tuning (filed, commit `d7849ce`) is an *acceptance sign-off* precondition, **not** a blocker to running the drill.

---

## 1. Deploy (copy-paste, from the repo root on the dev box)

```bash
# 1a. Dry-run sanity — confirm the power-watch install step prints, no error
bash deploy/deploy-pi.sh --dry-run 2>&1 | grep -iE "power.?watch|ERROR"

# 1b. Real deploy (rsync code + install/enable eclipse-powerwatch.service)
bash deploy/deploy-pi.sh
```

`step_install_power_watch_unit` is idempotent: cmp-if-changed install → daemon-reload on change → `enable --now` → restart-on-change (so new code actually runs). The legacy ladder had no standalone unit (it ran inside `eclipse-obd.service`, now deleted from the code) — nothing extra to uninstall.

### Post-deploy sanity (SSH to the Pi)

```bash
ssh chi-eclipse-01 "systemctl is-enabled eclipse-powerwatch.service && \
  systemctl is-active eclipse-powerwatch.service && \
  journalctl -u eclipse-powerwatch.service -b --no-pager | tail -5"
```

Expect: `enabled`, `active`, and a startup line like
`powerwatch service up: perTask=20s totalCap=45s vcellFloor=3.50V`.
**Hard fail if** the journal shows `No module named 'pi'` or any traceback (that is the V0.27.12-DOA class — the T8 guard makes this near-impossible, but verify on real hardware anyway).

---

## 2. IRL Acceptance Drill — spec §10 (run N cycles; CIO ratifies N, mirror Phase-1's 3)

Tail the watcher in one terminal during every cycle:
```bash
ssh chi-eclipse-01 "journalctl -u eclipse-powerwatch.service -f"
```

### Cycle A — full graceful loop (run ≥3 clean, consecutive)

1. Pi on car/wall power; `eclipse-powerwatch` active; `chi-srv-01` reachable.
2. **Remove external power** (key off / unplug). The proven `UpsMonitor` sustained rule (VCELL <3.95V/30s, or slope) fires the BATTERY transition → `eclipse-powerwatch` enters the window.
3. Verify the journal sequence:
   - `sustained-on-battery -- entering pre-shutdown window`
   - reachability: **reachable** → sync runs (`SyncClient.forcePush`); **unreachable** → `chi-srv-01 unreachable -- benign skip`. Either *resolves* the bounded window (success / benign / failed-after-retry — never hangs past the cap).
   - `pre-shutdown window resolved -- graceful poweroff` → `systemctl poweroff`.
4. Pi goes fully dark (confirm: `ping` stops, ~60s unreachable).
5. **Restore external power** (key on / ACC). Phase-1 EEPROM wake **auto-boots the Pi, zero human touch**. (This is the Phase-1↔Phase-2 join — the whole loop.)
6. Pi boots; confirm `eclipse-obd` + `eclipse-powerwatch` both `active` again.

### Cycle B — power-return abort (run ≥1)

1. Same as A steps 1–2 (induce sustained-on-battery).
2. **Restore power DURING the window** (before the poweroff fires — within the totalCap).
3. Verify: `power returned during window -- abort, resume normal op` and the Pi **does NOT power off** — it stays up and keeps collecting. No auto-boot needed (it never went down).

### Per-cycle checks

- [ ] If any sync fault occurred: `ssh chi-eclipse-01 "cat /home/mcornelison/Projects/Eclipse-01/data/powerwatch_outcome.json"` → a typed record (`server_unavailable` benign / `sync_failed_after_retry` / `real_error`). Producer-only — a consumer is out of scope by design.
- [ ] No `No module named` / traceback in the eclipse-powerwatch journal for the cycle.
- [ ] **Spool read-only re-verify**: power_log / sync state / data integrity unchanged by the cycle (no tuning edits — Spool SME read-only).

---

## 3. Acceptance criteria (Phase-2 closes when ALL hold)

- [ ] **N consecutive clean Cycle-A loops** (CIO-ratified N; Phase-1 used 3): on-battery → bounded sync/skip → graceful poweroff → unattended auto-boot, zero human touch.
- [ ] **≥1 clean Cycle-B**: power restored mid-window → abort + resume, no poweroff.
- [ ] Zero DOA-class journal errors across all cycles.
- [ ] Spool read-only sign-off (data integrity intact).
- [ ] **Sign-off note:** drill ran on interim bounds. Spool to confirm from real battery-runtime data whether `pi.powerWatch.{perTaskTimeoutSec,totalWindowCapSec,vcellFloorVolts}` should be tuned before declaring Phase-2 *fully* accepted (config-only change, no code — commit `d7849ce` tracks this).

---

## 4. Explicit scope (what this does NOT test — by design)

- **Bug-1 (original I-036 I/O-storm at-floor shutdown failure): eliminated by design, not deferred.** The in-app ladder that rode the battery to the floor is deleted (T9); that scenario no longer exists (spec §5/§7). Nothing to drill.
- **Phase-3** (Bluetooth/OBD reconnect on car/wall power): later, not in this acceptance.
- **Boot-progress instrument `CLEAN_COMPLETE`** (Finding A): demoted to last-priority housekeeping; not gating Phase-2.
- **Deferred housekeeping (non-blocking, flagged):** `drain_forensics` tool + `drain-forensics.service` are now vestigial (they only ever scraped the deleted ladder's journald telemetry); `SHUTDOWN_SUCCESS_MARKER` log string + ~15 docstrings carry stale "PowerDownOrchestrator" prose. Zero functional impact; a separate one-pass cleanup when convenient (the marker string is a Spool drain-audit grep contract — change it deliberately, not as a "tidy").
