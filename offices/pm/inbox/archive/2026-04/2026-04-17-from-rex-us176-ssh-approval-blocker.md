# 2026-04-17 — Rex → Marcus: US-176 SSH approval blocker

## What

US-176 (`deploy/deploy-pi.sh` + Pi OS setup verification + hostname rename)
deliverables that DO NOT need SSH are 100% complete:

- `deploy/deploy-pi.sh` written, with `--help`, `--init`, `--restart`,
  `--dry-run`, mutually-exclusive flag handling
- `deploy/deploy.conf.example` updated to the new conventions
  (`chi-eclipse-01`, `mcornelison`, `/home/mcornelison/Projects/Eclipse-01`)
- `deploy/deploy.conf` (gitignored local override) updated similarly
- `config.json` `deviceId` default flipped from `chi-eclipse-tuner` to
  `chi-eclipse-01`
- `tests/deploy/test_deploy_pi.sh` smoke test (29 assertions, all green)
- `tests/deploy/test_deploy_pi.py` pytest wrapper so the smoke test runs in
  the fast suite (3/3 PASS)
- `deploy/README.md` Pi tier section added with operator quickstart

`pytest tests/deploy/ -v` — 3/3 pass.
`python validate_config.py` — clean after the deviceId change.

## Blocker

This Ralph session ran inside a Claude Code interactive harness whose
permission allowlist refuses to execute live `ssh mcornelison@10.27.27.28`
commands without per-call human approval, and the approvals were not
granted. As a result, the live-Pi acceptance criteria for US-176 cannot be
satisfied from inside this session:

- `bash deploy/deploy-pi.sh --init` against the real Pi
- `bash deploy/deploy-pi.sh` (idempotency: re-run produces zero diff)
- `ssh mcornelison@10.27.27.28 'hostname'` returns `chi-eclipse-01`
- `ssh ... 'ls /home/mcornelison/Projects/Eclipse-01/src/pi/main.py'`
- `ssh ... '~/obd2-venv/bin/python -c "import pygame; print(pygame.version.ver)"'`
- Hostname persistence across a Pi reboot (CIO step regardless)

Important: **the script itself was not observed to fail** — it was simply
not run against a live Pi. The dry-run/help/flag-parsing surface is fully
exercised offline and the smoke test confirms the script emits the right
DRY-RUN ssh and DRY-RUN rsync intentions when invoked with `--dry-run`.

This is an environment access constraint at the agent harness layer, not
an SSH-to-Pi failure. Running `bash deploy/deploy-pi.sh --init` from a
normal git-bash terminal where SSH commands aren't gated should work.

## Recommendation

Operator (CIO) runs the following from a normal git-bash terminal in
`Z:/o/OBD2v2`:

```bash
# 1. Pre-flight (no Pi needed):
bash deploy/deploy-pi.sh --help
bash deploy/deploy-pi.sh --dry-run            # preview default mode
bash deploy/deploy-pi.sh --init --dry-run     # preview --init

# 2. Live SSH gate:
ssh mcornelison@10.27.27.28 'hostname'        # confirm Pi reachable

# 3. First-time Pi bootstrap:
bash deploy/deploy-pi.sh --init

# 4. Verify acceptance:
ssh mcornelison@10.27.27.28 'hostname'                                                     # expect: chi-eclipse-01
ssh mcornelison@10.27.27.28 'ls /home/mcornelison/Projects/Eclipse-01/src/pi/main.py'       # expect: file path
ssh mcornelison@10.27.27.28 '~/obd2-venv/bin/python -c "import pygame; print(pygame.version.ver)"'  # expect: a version string

# 5. Idempotency (run twice, second produces zero rsync transfer):
bash deploy/deploy-pi.sh
bash deploy/deploy-pi.sh
```

## Sprint contract status

US-176 is being marked `passes: false` in `sprint.json` per the strict
"partial completion = false" rule. The completion notes call out the
live-verification gap so the next session (or the operator) can close it
out by running the steps above.

If you'd rather treat this as `passes: true` once the operator confirms
the live steps, ping me and I'll flip the flag.

## Permission allow-list note

The local `Bash(ssh *)` allow rule in `offices/ralph/.claude/settings.local.json`
appears not to be matching plain `ssh mcornelison@10.27.27.28 hostname`
invocations. Worth investigating whether the pattern needs to be
`Bash(ssh:*)` (colon style, like `Bash(python:*)`) or whether the harness
needs different permission grammar — separate from this story but a
recurring future blocker for anything Ralph does on the Pi side.
