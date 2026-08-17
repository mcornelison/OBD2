from=Rex(Dev); to=Marcus(PM); date=2026-08-02; topic=US-513 RCA closed + a live ordering defect found in the BL-025 safety net; audience=mixed; urgency=medium; refs=US-513,BL-025,US-512

# US-513 closed — plus one defect the RCA turned up

Full write-up: `docs/rca/2026-08-02-us513-bt-rfkill-soft-block-origin-rca.md`. Commit `0341e6d`.

## The RCA answer, in one line

**Origin unprovable; project exonerated.** No project code or deploy path can produce a soft-block —
zero `rfkill block`, `nmcli radio off`, `hciconfig down`, `systemctl stop bluetooth`, or
`bluetoothctl power off` anywhere in `src/`, `scripts/`, `deploy/`. Every radio verb the repo ships
is restorative. Consistent with Atlas's manual-debug-artifact hypothesis, which is the only
explanation left once project code is excluded.

I did **not** name a culprit, because all three forensic sources are gone: the saved-state file was
overwritten by the 07-31 recovery (`mtime` now 07-31 20:26, and `rm -f /var/lib/systemd/rfkill/*`
ran), the journal retains only back to **07-26**, and `~/.bash_history` covers only the recovery
session. A named cause here would have been a guess dressed as a finding.

## The thing you actually need to know

**The safety net had a boot-ordering race, and it is fixed but not yet deployed.**

`eclipse-rfkill-unblock.service` ordered itself `After=systemd-rfkill.service` — the *producer* half,
which its header correctly calls "the fix". Nothing ordered the *consumer* half. Neither
`rfcomm-bind.service` nor `eclipse-obd.service` declared any relationship to it, so systemd was free
to start all three concurrently. On the Pi's 2026-07-31 boot:

```
eclipse-rfkill-unblock.service   ActiveEnter = 20:25:59
rfcomm-bind.service              ActiveEnter = 20:25:59      <- same second
```

Harmless that boot (the block had been zeroed by hand). On the one boot where a block *is* saved it
is a coin flip: rfcomm binds against a dark adapter, and **every unit still reads `active`** — the
exact "green-looking unit on a dark adapter" the unit's own header set out to prevent.

Why no test caught it: the existing test asserted this ordering against `unit_manifest.START_ORDER`,
a hand-ordered **Python tuple**. `unit_manifest`'s header says its ordering is "grounded in the
units' own declarations, NOT invented" — and the unblock-before-rfcomm claim was the one entry with
no declaration behind it. Sixth sighting of this sprint's two-correct-halves shape.

Fixed with `Before=rfcomm-bind.service eclipse-obd.service`, plus 5 anti-drift tests and a repo-wide
static guard (`tests/deploy/test_no_radio_disable_in_project.py`) that keeps the exoneration above
true by construction rather than by audit date.

**Deploy note:** no deploy-script change needed — `step_install_rfkill_unblock` is `cmp -s`-guarded,
so the changed unit installs + `daemon-reload`s on the next routine deploy. **Until that deploy runs,
the race is still live on the Pi.** Worth folding into the V0.29.24 deploy rather than waiting.

## Two calls that are yours / the CIO's, not mine

1. **Pi journal retention (~1 week).** This is the single reason the RCA cannot close harder — 07-03
   was ~3 weeks outside the window. A `SystemMaxUse=` / `MaxRetentionSec=` bump would make the next
   slow-burn fault forensically answerable. It is a box-config change, so I did not touch it.
2. **One discriminator left untested:** whether `bluetoothctl power off` can itself produce a *saved*
   block. Settling it means disabling a radio on the car Pi and rebooting. I declined under the
   standing "never disable a radio on the Pi remotely" rule (the 07-19 `nmcli radio wifi off`
   stranding). Safe path: bench Pi, or the car Pi with the CIO present. It changes no conclusion —
   the project doesn't issue that command either way.

## Gate

`tests/deploy` + `tests/pi/ops` = exit 0 (374 + 25 new). Ruff clean. Not run in-loop per TD-059:
full pytest + mypy — but this touches one systemd unit and two test files, no Python source.

— Rex
