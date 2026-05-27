---
id: F-080
parent: E-004
status: pending
renamedFrom: B-080
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-080: Pi clock jumps ~23h forward post-reboot (RTC drift / timesyncd) -- Spool's Bug 5

| Field | Value |
|---|---|
| Priority | Low (P3 -- observability; corrupts timestamps until NTP catches up) |
| Status | Pending (V0.28+ candidate; Spool said "file if it recurs" -- it recurred at the drain-18 boot 2026-05-12) |
| Category | pi / clock / observability |
| Size | S |
| Related | Spool 2026-05-12 v0277-addendum note (Bug 5); interacts with Spool's Bug 4 (drain 18 unclear close -- one hypothesis was the clock jump) + I-030/US-330 (startup_log writer parses journal timestamps) |
| Created | 2026-05-12 |

## Description

Spool 2026-05-12 (post-Pi-recovery, after drain 18 + reboot): post-reboot `power_log` timestamps show `2026-05-13` -- ~23 hours forward of wall time (it was 2026-05-12). NTP eventually catches up but late. The Pi's RTC battery may be dead, OR `systemd-timesyncd` is misconfigured / slow to sync on boot. Spool's original note said "file for V0.28+ if it recurs" -- it recurred at the drain-18 boot, so filing now.

## Impact

- Any row written between boot and the NTP catch-up gets a wrong timestamp (~23h forward). Affects `power_log`, `realtime_data`, `connection_log`, `battery_health_log`, `startup_log` -- everything timestamped in that window.
- Confounds forensic analysis (Spool's Bug 4 -- drain 18's `end_timestamp=NULL` -- listed "Pi clock jumped 23 hours" as one of three candidate causes; can't cleanly disambiguate while this is unfixed).
- The V0.27.7 US-330 startup_log writer parses `journalctl` timestamps -- if the journal itself has the bad clock, `current_boot_first_entry_ts` etc. inherit it.

## Hypotheses

- (a) RTC battery dead -- the Pi 5 has an RTC; if its coin cell is flat, the clock resets to a stale value on every cold boot until NTP fixes it. Check `timedatectl` / `hwclock` on the Pi.
- (b) `systemd-timesyncd` not running early enough / no NTP server reachable on boot before the Pi has WiFi -- the clock stays wrong until the network + timesyncd both come up. Check `systemctl status systemd-timesyncd` + `journalctl -u systemd-timesyncd`.
- (c) Some boot-time process sets the clock from a stale source (a saved-state file?) before timesyncd corrects it.

## Fix candidates

- If (a): replace the RTC coin cell (hardware -- CIO task) OR configure `fake-hwclock` so the clock at least persists the last-known-good time across reboots (a save-on-shutdown / restore-on-boot of the wall clock; standard on Pis without a good RTC).
- If (b): ensure `systemd-timesyncd` is enabled + has a reachable NTP server; consider `chrony` (faster initial step) or add `RTCFileMode` / a pre-network time source; order the data-writing services `After=time-sync.target` so they don't write rows before the clock is right.
- If (c): find the offending process; have it not touch the clock, or only set it from a trusted source.

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: `timedatectl`, `systemctl status systemd-timesyncd`, `journalctl -u systemd-timesyncd -b`, check the RTC (`hwclock -r` / Pi 5 RTC config) on chi-eclipse-01 -- identify which hypothesis matches
- [ ] Fix lands per the cause (RTC cell replace + fake-hwclock, or timesyncd/chrony config, or the offending-process fix)
- [ ] Post-fix: a Pi reboot's first post-boot `power_log` / `startup_log` row has a timestamp within a minute of wall time (not ~23h forward)
- [ ] (Bench) reboot the Pi 2-3 times; timestamps correct each time

## Source

- Spool 2026-05-12 inbox note `2026-05-12-from-spool-v0277-addendum-drive12-independent-work.md` (Bug 5: "Post-reboot timestamps show 2026-05-13 -- 23 hours forward of wall time. NTP eventually catches up but late. ... P3 observability item -- file for V0.28+ if it recurs.") -- recurred at the drain-18 boot, hence this filing.
