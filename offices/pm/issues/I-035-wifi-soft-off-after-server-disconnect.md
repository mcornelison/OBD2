# I-035: WiFi soft-disables (rfkill / NM-radio-off) on Pi after extended server-unreachable / OBDLink-absent periods; manual `nmcli radio wifi on` + SSID re-select required to recover

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High (P1)                 |
| Status       | Open (V0.27.10 candidate) |
| Category     | infrastructure / network / NetworkManager / combo-chip |
| Found In     | Unknown — code grep shows no eclipse-obd code path explicitly toggles WiFi radio state. Likely NetworkManager auto-quirk, driver behavior under combo-chip stress, or a deploy/install script side-effect. |
| Found By     | CIO (Mike) 2026-05-13 -- post-pharmacy-run session; PM (Marcus) reproduced "Pi unreachable" symptom server-side |
| Related B-   | I-025 (BT reconnect with no backoff -- combo-chip starvation hypothesis; OS-side `wifi.powersave = 2` mitigation already deployed per deploy-pi.sh and verified post-2026-05-13 redeploy); I-034 (SQLite disk-I/O lockup -- separate bug that happened concurrently; do NOT conflate) |
| Created      | 2026-05-13                |

## Description

After some period of running with the OBDLink LX out of BT range AND/OR server-unreachable (full mechanism not yet characterized), the Pi's WiFi radio becomes **soft-disabled**. The Pi is fully alive (responsive on local console / USB serial), but `wlan0` is down, `nmcli radio wifi` reports `disabled`, the Pi is invisible to the network (gateway returns `Destination host unreachable`), and **CIO must physically reach the Pi to manually re-enable WiFi (`nmcli radio wifi on`) AND re-select the home SSID** before the Pi can be SSH'd into again.

CIO empirical contrast: pre-V0.27, the WiFi was rock-solid; the Pi stayed network-reachable through long idle periods without user intervention. Some change in the V0.27.x epoch (or a combination of changes) introduced this regression.

## Steps to Reproduce

Today's repro (1 occurrence; full repro path TBD):

1. Boot Pi, start eclipse-obd service (CIO had Pi on wall power for debug since the day before)
2. Drive 12 captured cleanly (3591 rows, 19:01:59-19:10:24 UTC)
3. ~30 min of mixed activity: drain ladder firings, sync attempts, BT-reconnect attempts to absent OBDLink
4. ~19:38 UTC: SQLite disk-I/O error flood begins (I-034 -- separate bug, mechanism unrelated)
5. ~20:50 UTC (1h12m after I-034 onset): Pi disappears from network entirely. `ping 10.27.27.28` → `Destination host unreachable` from gateway; SSH timeout.
6. CIO physically inspects Pi: alive, but WiFi soft-disabled.
7. CIO runs `nmcli radio wifi on` AND re-selects home SSID. Pi reachable again.
8. PM redeploys eclipse-obd via `bash deploy/deploy-pi.sh`; service comes up clean; no recurrence in the immediate post-deploy window.

## Expected Behavior

WiFi radio stays on indefinitely. SSID profile persists across reboots and across any code-side power-management decisions. If WiFi is automatically disabled, it's by explicit user action (`nmcli radio wifi off`) or an OS-level quirk we configure (none currently).

## Actual Behavior

WiFi radio gets soft-disabled by some agent. Recovery requires hands-on intervention -- defeats the entire B-063 fuse-box "always-on telemetry" model AND defeats remote-debug capability.

## Impact

- **Pi becomes unreachable** -- no SSH, no remote restart, no remote diagnostic queries. CIO must physically reach Pi.
- **Telemetry sync stops** -- any data already on Pi cannot reach the server until WiFi is restored.
- **Update/redeploy blocked** -- can't push fixes to Pi without physical access.
- **Recurring** per CIO -- this is the second WiFi-loss incident in the V0.27 epoch (first noted 2026-05-11 per I-025; root-caused at the time to Pi 5 combo-chip + wifi.powersave default; mitigated by `wifi.powersave = 2` drop-in -- but that mitigation alone is not sufficient based on today's recurrence).

## What we already know (initial PM investigation 2026-05-13)

- Code grep for `rfkill|nmcli|wpa_cli|wpa_supplicant|iwconfig|wlan0|wifi|power_save|powersave` across `src/`: 7 files match, but on inspection NONE explicitly disable WiFi radio. `src/pi/power/power.py:_enablePowerSaving()` only dims display + slows battery monitor polling -- does NOT touch WiFi.
- `wifi.powersave = 2` drop-in IS deployed (`deploy/deploy-pi.sh` Step "Installing NetworkManager wifi.powersave=2 drop-in" reports "already current" post-2026-05-13 redeploy).
- Today's redeploy + service restart returned Pi to normal operation, but did NOT exercise the failure mode (no extended idle since restart).
- Concurrent with I-034 (SQLite disk-I/O error flood) but mechanism appears unrelated -- I-034 was DB-layer, I-035 is network-stack.

## Likely investigation directions (for Ralph to refine)

1. **`journalctl -u NetworkManager`** during a failure window -- look for `nmcli radio wifi off` invocations OR automatic disable events ("WiFi disabled by user", "radio kill switch", etc.)
2. **`rfkill list all`** state -- when failure happens, is it soft-block or hard-block? Who set it?
3. **dmesg / kernel log** -- combo-chip driver may emit a `disabling wifi due to coexistence pressure` style warning
4. **Audit deploy/install scripts** -- check `deploy/deploy-pi.sh`, `deploy/install-service.sh`, and any systemd drop-ins for any rfkill / nmcli / NM-config side effects (`grep -rE 'rfkill|nmcli radio|wifi[ .](?:off|disable)' deploy/`)
5. **Pi-OS-level auto-disable feature?** Check `/etc/NetworkManager/conf.d/`, `/etc/NetworkManager/system-connections/`, and `nmcli connection show` for any auto-disable timers on the home SSID profile.
6. **Combo chip thermal / coexistence escalation?** Pi 5 BCM4345/6 may have a driver path that disables one radio under sustained co-channel conflict. Check `dmesg` for `brcmfmac` errors during a failure window.

## Acceptance Criteria (PM-level; Ralph fills in implementation)

- [ ] Root cause identified: name the specific agent that toggles WiFi off (NetworkManager rule, rfkill caller, kernel driver, deploy script side-effect, etc.)
- [ ] Fix applied: WiFi radio stays on through 24h+ continuous Pi uptime including BT-absent intervals, sync-failure intervals, and at least one I-034 disk-I/O event
- [ ] SSID profile persists: no "re-select home SSID" step required after any failure recovery
- [ ] Synthetic regression test if a code-side trigger is found; documented systemd/NM config drop-in if it's OS-side
- [ ] Real-world validation: leave Pi on wall power 24h+ with OBDLink unplugged; assert `nmcli radio wifi` reports `enabled` throughout AND Pi remains pingable

## Cross-references

- I-025 (BT reconnect no-backoff -- the combo-chip starvation hypothesis; `wifi.powersave = 2` mitigation deployed but insufficient)
- I-034 (SQLite disk-I/O lockup -- concurrent today but mechanism unrelated; cross-reference for triage convenience only)
- I-033 (BT-no-reconnect-after-engine-cycle -- same Drive 12 analysis session; orthogonal bug)
- B-063 (fuse-box wiring DONE 2026-05-12 -- makes the "always-on Pi must stay network-reachable" property load-bearing)

## Source

CIO Mike 2026-05-13: "I had to manually turn 'ON' the pi's wifi and choose the home wifi ssid. I think we have a bug somewhere in the code that disconnects the WiFi and turns it off if it can't connect to the server after some period. Because I know for a fact early on, before version zero dot twenty seven, the WiFi was always up and running, and I never had any connection issues before."

PM (Marcus) corroborates: Pi was reachable through 19:30:49 UTC (last successful sync); ping from PM workstation at ~20:50 UTC returned `Destination host unreachable`; CIO manually restored WiFi shortly after; Pi reachable again for redeploy.
