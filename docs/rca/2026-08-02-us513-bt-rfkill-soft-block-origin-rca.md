# RCA — origin of the persisted Bluetooth rfkill soft-block (~2026-07-03)

| | |
|---|---|
| **Story** | US-513 (F-120, E-OPS) — RCA: why BT got soft-blocked ~07-03 (confirm origin so it can't recur) |
| **Author** | Rex (Ralph / Dev) |
| **Date** | 2026-08-02 |
| **Sprint** | 69 / V0.29.24 (dashboard wiring + capture hardening) |
| **Status** | COMPLETE — origin **UNPROVABLE at this remove**; project **exonerated**; mitigation found **insufficient** and hardened |
| **Refs** | BL-025, V0.29.22 hotfix, `deploy/eclipse-rfkill-unblock.service`, Atlas 2026-07-31 live find, US-512 |
| **Live evidence** | `Chi-Eclips-01` @ 10.27.27.100, read-only probes 2026-08-02 |
| **Artifacts shipped** | `deploy/eclipse-rfkill-unblock.service` (ordering fix), `tests/deploy/test_no_radio_disable_in_project.py` (new), `tests/deploy/test_rfkill_unblock_install.py` (+5 tests) |

> **Scope rule (this story):** research. AC4 says *"no code change required unless a project-side cause is
> confirmed."* No project-side cause was confirmed — but AC2 offers a fork: *"document the finding + a
> prevention **(or confirm the unblock service is sufficient mitigation)**."* I could **not** confirm
> sufficiency: the safety net has a verified ordering race. The prevention half of AC2 is therefore
> in scope, and is what this story ships.

---

## 1. The question

Capture died ~2026-07-03 (zero rows; the 07-27 IRL drive captured nothing). On 2026-07-31 Atlas found
the cause live: a **saved** Bluetooth soft-block —

```
/var/lib/systemd/rfkill/platform-107d50c000.serial:bluetooth = [1]
```

— which `systemd-rfkill` faithfully **restores on every boot**. BT came up blocked, `eclipse-obd`
could never reach the OBDLink LX, and every layer above reported an honest "no adapter" while the
real fault sat one level below the entire application stack.

That answered *what*. US-513 asks **why the `[1]` was ever written**, and whether anything in this
project can write it again.

---

## 2. Verdict

| Question | Answer |
|---|---|
| Can any project code / deploy path cause a soft-block? | **No.** Exhaustive audit; every radio verb the repo ships is *restorative*. |
| What wrote the `[1]`? | **Unprovable.** All three forensic sources are destroyed or out of range. |
| Consistent with Atlas's hypothesis (manual debug artifact, persisted at shutdown)? | **Yes** — and it is the only hypothesis left standing once project code is excluded. |
| Is `eclipse-rfkill-unblock.service` sufficient mitigation? | **No — it had a boot-ordering race.** Found, fixed, pinned. |

---

## 3. Why the origin is unprovable (state this plainly rather than guess)

Three independent sources could have dated the original write. All three are gone:

| Source | State on 2026-08-02 | Why it can't answer |
|---|---|---|
| The saved-state file itself | `mtime = 2026-07-31 20:26:02`, contents `0` | The 07-31 hotfix **overwrote** it (and `sudo rm -f /var/lib/systemd/rfkill/*` ran during recovery). The original write timestamp is destroyed. |
| systemd journal | Oldest retained boot = **2026-07-26 12:39:54** | 07-03 predates the retained window by ~3 weeks. |
| `~/.bash_history` | 9.6 KB, `mtime 2026-07-31 14:47` | Holds only the 07-31 recovery session. Also: `ssh host "cmd"` is non-interactive and never appends to history, so agent-issued commands were never captured at all. |

**This is the honest-instrument answer.** A named culprit here would be a fabrication dressed as a
finding — precisely the failure mode this project treats as worse than an admitted unknown. What the
evidence *can* do is bound the answer, which section 4 does.

One corroborating detail, well short of proof: the retained `bash_history` contains **no `rfkill
block` of any kind** — every rfkill line in it is an `unblock`. Consistent with "the block was not
issued from an interactive shell on this account", but the file is too short and too late to carry
weight.

---

## 4. The project is exonerated — and this is the strong finding

Exhaustive audit of `src/`, `scripts/`, and `deploy/` for every command that can disable a radio:

| Command class | Occurrences in shipped code |
|---|---|
| `rfkill block` | **0** |
| `nmcli radio … off` | **0** |
| `hciconfig <dev> down` | **0** |
| `systemctl stop/disable/mask bluetooth` | **0** |
| `bluetoothctl power off` | **0** |

Every radio verb the project ships points the other way:

- `scripts/pair_obdlink.sh:224` — `bluetoothctl power on`
- `scripts/pair_obdlink_driver.py:300` — `_send(child, "power on", …)`
- `deploy/deploy-pi.sh:838` / `eclipse-rfkill-unblock.service:65` — `rfkill unblock all`
- `scripts/connect_obdlink.sh` — `rfcomm bind` / `rfcomm release` (one layer *above* the radio)

`rfcomm release` is worth calling out because it is the closest thing to a teardown the project
performs: it removes a **kernel binding table entry**, not radio state, and cannot produce an rfkill
block. US-512 documents the same boundary from the other side.

**Conclusion:** no deploy, no service, no script, and no orchestrator path can produce the artifact.
Combined with §3, the surviving explanation is an **external/manual action on the box** — a debug
session, a desktop Bluetooth toggle, or a stray `rfkill block` — that `systemd-rfkill` then dutifully
saved at the next shutdown, exactly as designed. That matches Atlas's hypothesis, and the 07-03 date
coincides with a live-Pi BT debug session (commit `ad59561`, *"closeout(atlas): 2026-07-03 session —
A-17 OBD thread-race RCA + hotfix + **pairing-saga**"*). Suggestive; not proof, and recorded as such.

### 4.1 One discriminator deliberately left untested

Whether `bluetoothctl power off` can itself produce a *saved* soft-block (as opposed to merely
powering the adapter down) is the one mechanism question I did not settle. Settling it requires
disabling the radio on a live box and rebooting.

I did not do that, and the reason is a standing project rule: **do not disable a radio on the car Pi
remotely.** That rule exists because of the 2026-07-19 `nmcli radio wifi off` incident that stranded
the Pi off-network across four reboots. The blast radius here is smaller (BT is not the control
channel) but the shape is identical, the box owes an engine-on validation drive, and the answer would
not change any conclusion above — the project doesn't issue that command either way.

**To settle it safely:** run it on a bench Pi, or on the car Pi with the CIO physically present, and
check `rfkill list` + `/var/lib/systemd/rfkill/*` before and after a reboot.

---

## 5. The mitigation was NOT sufficient — a verified ordering race

Auditing whether `eclipse-rfkill-unblock.service` is a sound standing net turned up a real defect.

The unit reasons carefully about the **producer** side, and its header is explicit that this is the
whole fix:

```
After=systemd-rfkill.service bluetooth.service
```

> *"`After=systemd-rfkill.service` is load-bearing, not decoration. … Unblocking BEFORE it runs simply
> lets it re-block the radio afterwards — a green-looking unit on a dark adapter."*

Correct, and only **half** of the ordering problem. Nothing ordered the **consumer** side. Queried on
the Pi:

```
$ systemctl show eclipse-rfkill-unblock.service -p Before
Before=multi-user.target shutdown.target          # nothing project-owned

$ systemctl show rfcomm-bind.service -p After
After=… bluetooth.service … bluetooth.target      # no mention of the unblock

$ systemctl show eclipse-obd.service -p After
After=… bluetooth.target network.target …         # no mention of the unblock
```

All three units are merely `After=bluetooth.*`, i.e. **mutually unordered**. systemd is free to start
them concurrently — and did:

```
eclipse-rfkill-unblock.service   ActiveEnterTimestamp = Fri 2026-07-31 20:25:59 CDT
rfcomm-bind.service              ActiveEnterTimestamp = Fri 2026-07-31 20:25:59 CDT
```

**The same second.** On that boot the saved block had already been zeroed by hand, so the race was
harmless and invisible. On the one boot where a block *is* saved, it is a coin flip: `rfcomm-bind`
binds `/dev/rfcomm0` against a still-dark adapter, `eclipse-obd` opens a dead tty, and **every unit
reports `active`** — the exact "green-looking unit on a dark adapter" the unit's own header set out
to prevent.

### 5.1 Why no test caught it (the recurring shape)

`tests/deploy/test_rfkill_unblock_install.py` *did* assert the ordering — against
`unit_manifest.START_ORDER`, a hand-ordered Python tuple:

```python
def test_unitManifest_ordersTheUnblockBeforeTheRfcommBind():
    assert order.index(UNIT_NAME) < order.index("rfcomm-bind.service")
```

`unit_manifest.py`'s own header states its ordering is *"grounded in the units' own declarations, NOT
invented"* — and then lists the declarations it relies on, **none of which mention the unblock unit.**
So the manifest's unblock-first claim was the single ordering in that tuple with nothing behind it.
The manifest is not decorative (`obdctl` sequences its own start/stop by it) — but it **cannot order
boot**, and boot is precisely when a restored soft-block bites.

This is Sprint 69's recurring failure shape for the sixth time (US-494/499/502/503/505): two halves
each internally correct, nothing carrying the claim across, and a green test on one half.

---

## 6. What shipped

**Fix** — `deploy/eclipse-rfkill-unblock.service`:

```
Before=rfcomm-bind.service eclipse-obd.service
```

`Before=` and deliberately **not** `Wants=`: it orders those consumers when they are already in the
boot transaction, and must never pull them in. No cycle is introduced (the unblock is `After=
bluetooth.service`; neither consumer is an ancestor of it). Deploy needs no change — `deploy-pi.sh`
`step_install_rfkill_unblock` is `cmp -s`-guarded, so the changed unit installs and `daemon-reload`s
on the next routine deploy.

**Prevention** — `tests/deploy/test_no_radio_disable_in_project.py` (new, 25 tests): a repo-wide
static guard making §4's exoneration a standing invariant rather than a point-in-time audit. US-512
already guards this at runtime, but only for two helpers and only for commands they actually emit; a
new script or deploy step is invisible to it.

Guard design notes worth keeping:

- Patterns match **argv lists** as well as shell strings — the self-test caught on its first run that
  a whitespace-only separator would see every `sudo rfkill block` and miss every
  `subprocess.run(["rfkill", "block", …])`, which is the form `bluetooth_helper` actually uses.
- `\bblock\b` after a token separator, so `rfkill unblock all` is not condemned — otherwise the guard
  would flag the fix for the outage it exists to prevent. Pinned by an explicit permit-list test.
- Whole-line `#` comments are stripped (US-501's lesson): `bluetooth_helper.py` and
  `obd_connection.py` both *document* these forbidden commands, and a raw-text scanner would flag the
  prose explaining the rule.
- `tests/` is not scanned — US-512's guards assert on these strings literally.
- Escape hatch: a greppable `radio-guard-exempt` marker on the line, per the project's
  explicit-hatch-over-drift rule.

**Anti-drift** — `tests/deploy/test_rfkill_unblock_install.py` (+5 tests): the manifest may no longer
claim an ordering that no systemd directive implements; and no consumer may declare `Before=` the
unblock (which would form a cycle systemd resolves by silently **dropping** an edge — reinstating the
race with no visible error).

---

## 7. Recommendations

1. **Sufficient going forward? Yes, now.** Unit is `enabled` + `active` (`RemainAfterExit=yes`),
   repo-managed, re-asserted on every routine deploy, and — as of this story — actually ordered
   before the units that need the radio.
2. **The ordering fix reaches the Pi only on the next deploy.** Until then the race remains, latent.
3. **Journal retention (~1 week) is the reason this RCA cannot close harder.** A `SystemMaxUse=` /
   `MaxRetentionSec=` bump on the Pi would make the next slow-burn fault forensically answerable.
   Filed as a suggestion for PM, not built here (out of scope, and it is a box-config change).
4. **Preserve artifacts before clearing them.** The 07-31 recovery `rm -f`'d and rewrote the one file
   that carried the origin timestamp. Understandable under pressure, but `cp` before `rm` costs
   nothing and is the difference between a provable and an unprovable RCA.
5. **No further code change is warranted for the origin itself** — there is nothing project-side to
   fix, and §4's guard is the durable answer to "can it come back from our side".
