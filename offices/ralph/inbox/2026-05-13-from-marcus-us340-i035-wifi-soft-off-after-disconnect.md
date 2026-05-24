# US-340 / I-035 — WiFi soft-disables on Pi; manual `nmcli radio wifi on` + SSID re-select required (P1)

**From:** Marcus (PM)
**To:** Ralph (Developer)
**Date:** 2026-05-13
**Sprint:** V0.27.10 bug-fix patch (interactive — no sprint.json this time; CIO will work with you live)
**Branch:** `sprint/sprint36-bugfixes-V0.27.10` (already created)
**Priority:** P1 (Pi unreachable → no remote SSH, no remote redeploy, no remote telemetry sync)
**Size estimate:** M-L (PM read; this story is INVESTIGATION-FIRST — Ralph may need to spike before scoping the fix)

---

## What broke

On 2026-05-13, the Pi disappeared from the network ~1h12m after the SQLite disk-I/O error flood started (~20:50 UTC). `ping 10.27.27.28` → `Destination host unreachable` from gateway; SSH timed out from the PM workstation.

CIO physically inspected: Pi was alive but **WiFi was soft-disabled**. CIO had to:
1. Manually run `nmcli radio wifi on` (or use a GUI toggle)
2. Re-select the home SSID

…before the Pi became network-reachable again.

**CIO empirical contrast (the strong tell that this is a code/config regression, not a hardware flake):** *"early on, before V0.27, the WiFi was always up and running, and I never had any connection issues before."* Some change in the V0.27.x epoch introduced this regression.

## Why this is a separate story from I-034

Concurrent with the SQLite disk-I/O lockup (I-034) but the **mechanism is different**:
- I-034 (US-339): DB-layer; `sqlite3.OperationalError` on long-lived connection; healed by process restart.
- I-035 (this story, US-340): Network-layer; WiFi radio toggled off; healed by `nmcli radio wifi on`.

Do NOT try to fix this in I-034's story. They share an IRL gate (long-uptime survival) but the code paths are unrelated.

## What we already know (PM initial dig — save you the first hour)

- **Our code is NOT the explicit disabler.** Grep across `src/`: `rfkill|nmcli|wpa_cli|wpa_supplicant|iwconfig|wlan0|wifi|power_save|powersave` matches 7 files but NONE explicitly disable WiFi radio. `src/pi/power/power.py:_enablePowerSaving()` ONLY dims the display + slows battery monitor polling. So whoever's flipping the switch, it's not us via the obvious path.
- **`wifi.powersave = 2` mitigation IS deployed.** `deploy/deploy-pi.sh` step "Installing NetworkManager wifi.powersave=2 drop-in" reports "already current" post-2026-05-13 redeploy. This was the I-025 (2026-05-11) mitigation for Pi 5 combo-chip starvation. **It's clearly not sufficient on its own** — today's failure recurred WITH the mitigation in place.
- **The redeploy + service restart fixed reachability** but did NOT exercise the failure mode (no extended idle since restart). So we can't confirm the redeploy itself addressed anything — it just returned the Pi to a working baseline.

## Investigation directions (pick one or run all four in parallel)

### Direction 1: NetworkManager journal (highest-yield first cut)

```bash
ssh chi-eclipse-01 'journalctl -u NetworkManager --since "1 hour before failure window" --until "after CIO restored wifi" --no-pager'
```

Look for: `nmcli radio wifi off` invocations, `WiFi disabled by user`, `radio kill switch`, `set-radio false`. **Whoever or whatever toggled the radio left a trace here.** That trace names the culprit.

### Direction 2: rfkill state when failure recurs

If we can catch it live next time:
```bash
rfkill list all                  # which radio? soft-block or hard-block?
journalctl --grep rfkill         # who set the block?
```

### Direction 3: Audit deploy / install scripts + systemd drop-ins

```bash
grep -rEn 'rfkill|nmcli radio|wifi[ .](?:off|disable)' deploy/
grep -rEn 'rfkill|nmcli radio|wifi[ .](?:off|disable)' /etc/systemd/system/ /etc/NetworkManager/   # on the Pi
```

Side-effects in our deploy/install scripts are within scope to fix here.

### Direction 4: NetworkManager auto-disable on connectivity-failure quirk

Some NetworkManager versions have a "disable wifi after N failed connectivity checks" code path. Check:

```bash
nmcli connection show <home-ssid-uuid>     # any auto-disable timer set?
cat /etc/NetworkManager/conf.d/*.conf      # any policy drop-ins?
nm-online --quiet ; echo $?                # is NM's connectivity-check enabled?
```

NM connectivity-check failures DO NOT normally disable WiFi, but if our `connectivity-check-uri` is misconfigured, who knows.

### Direction 5: Pi 5 combo-chip / brcmfmac kernel driver

```bash
dmesg -T | grep -iE 'brcmfmac|wifi|wlan'
```

Look for thermal warnings, coexistence-pressure messages, or driver disable events during the failure window.

## Acceptance (PM-level)

1. **Root cause identified + named.** The story does not close until we can answer "what specific agent toggled WiFi off?" with a citation (journal line, config file, code path).

2. **Fix applied.** Shape depends on root cause:
   - If our code → fix the code path + add a synthetic regression test
   - If our deploy/install scripts → fix the script + add an idempotency guard
   - If NetworkManager auto-quirk → add an `/etc/NetworkManager/conf.d/` drop-in that overrides the misbehaving policy (similar to the existing `disable-wifi-powersave.conf`); wire it into `deploy/deploy-pi.sh` so it deploys idempotently
   - If kernel driver → escalate to a documented OS-level workaround + record in `specs/`

3. **SSID profile persists.** No "re-select home SSID" step required after the fix. The home WiFi profile must auto-reconnect on radio-restore.

4. **IRL gate (post-deploy, shared with US-339 / I-034):** leave Pi on wall power 24h+ with OBDLink unplugged AND eclipse-obd running; assert:
   - `nmcli radio wifi` reports `enabled` throughout
   - Pi remains pingable from PM workstation
   - Pi auto-reconnects to home SSID after any transient WiFi blip
   - Zero `disk I/O error` lines in `journalctl -u eclipse-obd` (shared with I-034)

## Operational note for the investigation

The next time the Pi disappears from the network, **do not let CIO recover it immediately** — first capture diagnostic state if at all possible (rfkill list, journalctl tail, dmesg tail, nmcli state) via console / serial / HDMI keyboard. The failure is intermittent; we may not get many chances.

If you need to set up a "capture state on failure" hook now (small bash script + systemd timer that writes `nmcli radio wifi` / `rfkill list` / `journalctl -u NetworkManager --since 5min` to a file every minute), that's in scope for this story as a debugging aid.

## Cross-references

- `offices/pm/issues/I-035-wifi-soft-off-after-server-disconnect.md` — PM bug paper (full timeline + initial PM investigation)
- I-025 (BT reconnect no-backoff; combo-chip starvation hypothesis; `wifi.powersave = 2` mitigation deployed but insufficient for THIS bug)
- I-034 / US-339 (SQLite disk-I/O lockup; concurrent today; orthogonal mechanism; shares IRL gate)
- I-033 / US-338 (BT-no-reconnect after engine cycle; sibling V0.27.10 story)

## Ack expected

Confirm: (a) initial investigation direction (1/2/3/4/5 or hybrid), (b) "capture state on failure" hook in scope or split out, (c) any blockers. Then commit + push when first cut is ready. Expect this story to take longer than US-338 and US-339 because the root cause is genuinely unknown — happy to size up to L if Direction 1 doesn't surface a smoking gun quickly.
