# Lesson: a bench/validation instrument must target the DEPLOYED state, not the repo branch

**Owner:** Ralph · **Date:** 2026-05-18 · **Class:** orchestration-integrity (validation tier)
**Trigger:** Task 1 bench checklist Check A failed on the CIO's bench with
`ModuleNotFoundError: No module named 'src.pi.hardware.pld_sensor'`.
**Status:** corrected (Check A is now the dependency-free `pinctrl` form; bench
re-run PASSED). This finding records the generalizable lesson; it does NOT
reopen Task 1's regression-first conclusion (that verdict was independently
git-verified and stands).

---

## What happened

The Task 1 deliverable `phase2-bench-observations-checklist.md` Check A told the
CIO to run, on the Pi:

```
PYTHONPATH=.:src ~/obd2-venv/bin/python -c "from src.pi.hardware.pld_sensor import PldSensor ..."
```

It raised `ModuleNotFoundError` immediately. The instrument never ran.

## Root cause (git-cited, not inferred)

- The Pi runs the **deployed** build **V0.27.14 = `0125417`**.
- `git ls-tree 0125417 -- src/pi/hardware/pld_sensor.py` → **ABSENT**. The module
  does not exist in the deployed tree.
- `pld_sensor.py` was **created by `4edbdc1`** (the GPIO6 hotfix), which is
  **committed to the sprint branch but NOT deployed** (`eclipse-powerwatch`
  masked; hotfixes never pushed to the Pi — the standing deploy hazard).
- Therefore Check A imported a module that exists on the **repo branch** but not
  on the **target's actual running filesystem**.
- Secondary: a multi-line heredoc over SSH is paste-fragile (newline mangling).

The instrument was specified against the repo branch state I was reasoning from,
not against what is actually deployed where the instrument executes.

## The lesson (generalizable)

> **A validation/bench instrument is itself code that must run "as wired" — on
> the target, in the target's actual deployed state. Specify it against what is
> DEPLOYED, not against the repo branch you authored it from.**

This is the **same failure class as V0.27.12-DOA**: "written, but not where it
runs." There the production entrypoint was never proven to run as systemd
invokes it; here a *validation instrument* was never proven to run on the
*deployed* Pi. Both fail for the identical reason — an artifact validated
against the author's environment, not the execution environment.

It **generalizes spec §5's orchestration-proof principle to the validation
tier**: §5 already requires production components to prove they execute as
wired (systemd-parity + positive evidence). The same bar must apply to the
instruments that gate IRL acceptance — an instrument that cannot run on the
deployed target produces *absence of signal*, which is silently mistaken for
*absence of problem* (the exact anti-pattern the positive-evidence rule exists
to kill).

## Concrete rules adopted

1. **No project imports in a bench instrument that runs on a target whose deploy
   state differs from HEAD.** Prefer OS-level tools already on the target
   (`pinctrl`, `raspi-gpio`, `rpi-eeprom-config`, `systemctl`) over
   `from src...`. (Check A is now `sudo pinctrl set 6 ip pn` + `pinctrl get 6`.)
2. **Paste-safe / single-purpose.** Avoid multi-line heredocs over SSH; prefer
   one-line, copy-safe commands with a binary verdict.
3. **State the target's deployed version explicitly** in the instrument and
   confirm any referenced artifact exists in *that* version (`git ls-tree
   <deployed-sha> -- <path>`), not in HEAD.
4. **Deploy hazard is not a workaround path.** "Just deploy the branch so the
   import resolves" is forbidden here (no redeploy/unmask until the sequencer
   passes 5-cycle IRL). The instrument must work against the *current* deployed
   state without changing it.

## Scope / non-impact

- Task 1 regression-first conclusion: **UNCHANGED, still PASS** (git-verified
  independently; unaffected by this instrument defect).
- Check B (`rpi-eeprom-config` + physical poweroff): unaffected — OS-only, no
  project import. Left as-is. (It subsequently PASSED at bench.)
- Ownership: the flawed command originated in the Atlas spec/checklist and was
  carried faithfully; this is a shared-artifact correction, recorded here as a
  standing lesson for all future bench/validation instruments.
