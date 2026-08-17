# 2026-04-17 — Rex → Marcus: US-179 offline deliverables + live-Pi verification gap

## What

US-179 (`deploy/eclipse-obd.service` + install/uninstall-service.sh + TD-010
path drift cleanup) offline deliverables are complete:

### Service + install tooling
- `deploy/eclipse-obd.service` — stale paths fixed:
  - `User=pi` → `User=mcornelison`
  - `WorkingDirectory=/home/pi/obd2` → `/home/mcornelison/Projects/Eclipse-01`
  - `Environment=PATH=/home/pi/obd2/.venv/bin:...` → `/home/mcornelison/obd2-venv/bin:/usr/bin:/bin`
    (dedicated Pi venv, mirrors server's `~/obd2-server-venv` convention per
    Session 17 decision)
  - `ExecStart=/home/pi/obd2/.venv/bin/python src/main.py --config src/obd_config.json`
    → `/home/mcornelison/obd2-venv/bin/python src/pi/main.py`
    (no `--config` flag — `src/pi/main.py` resolves `config.json` via
    `Path(__file__)` already)
  - `StandardOutput=append:/home/pi/obd2/logs/service.log` and
    `StandardError=append:...` **removed** — journald is now the single log
    source (viewable with `sudo journalctl -u eclipse-obd -f`). Satisfies
    acceptance: "Service logs land in journalctl (not /home/pi/obd2/logs/)".
  - `After=network.target bluetooth.target` / `Wants=bluetooth.target`
    preserved. `Restart=on-failure`, `RestartSec=10`,
    `StartLimitIntervalSec=300`, `StartLimitBurst=5` preserved.

- `deploy/install-service.sh` — rewritten:
  - Defaults now `SERVICE_USER=mcornelison`, `INSTALL_PATH=/home/mcornelison/Projects/Eclipse-01`, `VENV_PATH=/home/mcornelison/obd2-venv`
  - New `--venv PATH` flag to decouple venv location from install path
    (old script assumed `$INSTALL_PATH/.venv` which violates the new convention)
  - Validates `src/pi/main.py` exists at install path (not `src/main.py`)
  - Drops logs/ directory creation (journald replaces on-disk logs)
  - Idempotent by design: service-file overwrite, `mkdir -p`, and
    `systemctl enable` are all safe to re-run. Satisfies acceptance:
    "install-service.sh idempotent: running it twice produces the same end state"

- `deploy/uninstall-service.sh` — cleanup pass:
  - `--keep-logs` kept as backward-compat no-op flag
  - Log-file removal loop dropped (nothing to remove — journald)

### TD-010 path drift cleanup
Fixed across US-179's `filesToTouch` list:
- `Makefile`: `run`/`run-dry` targets now point at `src/pi/main.py`. Deploy
  targets repointed from legacy `scripts/deploy*.sh` to `deploy/deploy-pi.sh`
  per TD-012's recommendation (new `deploy-restart` target added). `deploy-env`
  target dropped (env push is operator-managed per the new deploy philosophy;
  `scripts/deploy-env.sh` file itself left alone pending TD-012 cleanup).
- `README.md`: 7 stale `python src/main.py` refs fixed; project structure
  block updated to post-reorg tier layout (`src/pi/`, `src/server/`,
  `src/common/` subpackages).
- `deploy/README.md`: Quick Start + "What install-service.sh Does" updated
  to the new paths + idempotency note.
- `docs/cross-platform-development.md`: 3 in-scope refs fixed (lines 178,
  192, 229).
- `docs/testing.md`, `docs/hardware-reference.md`, `docs/deployment-checklist.md`
  — **scope extended** from TD-010's list: these docs contain the same kind
  of stale `src/main.py` / `/home/pi/obd2` references and are what operators
  read when setting up the Pi. Fixing only TD-010's 7 files would have left
  the US-179 acceptance grep with hits in `docs/` (which the grep
  authoritatively checks). Flagging the extended scope here so you can
  confirm the judgment call.

### Acceptance grep (US-179 #14)
```
grep -rn 'src/main.py\|/home/pi/obd2\|User=pi' deploy/ Makefile README.md docs/ .claude/
```
Zero hits outside `docs/superpowers/archive/` (which is historical reorg-design
record — intentionally preserved; the grep should logically exclude that
subtree).

### Tests + lint
- Full fast suite: **1873 passed, 1 skipped, 22 deselected, 1 flake** (278s).
  Flake: `tests/test_orchestrator_loop_exception_memory.py::test_loopContinuesAfterException`
  — passes in isolation (39s). This is the same class of cross-test
  state-leak flake documented in prior sessions (category-neighbor of the
  `test_verify_database.py` Windows subprocess flake); not related to US-179
  changes (nothing I touched is imported from orchestrator loop code).
- Deploy suite: `pytest tests/deploy/ -v` — 3/3 pass (34s, bash smoke test
  + pytest wrappers; zero change from US-176 baseline).
- Ruff: 4 pre-existing errors in `src/server/ai/ollama.py` + `tests/test_remote_ollama.py`
  (baseline from Sweep 6 — not introduced by this story).
- `python validate_config.py` — all green (Project Structure / Dependencies /
  Environment / Configuration all OK).

## Blocker

Same harness SSH approval gate as US-176 (see
`offices/pm/inbox/2026-04-17-from-rex-us176-ssh-approval-blocker.md`). US-179
has the following live-Pi acceptance criteria that I cannot satisfy from
inside this session:

- `bash deploy/install-service.sh` against the real Pi
- `ssh ... 'sudo systemctl enable eclipse-obd && sudo systemctl start eclipse-obd'`
- `ssh ... 'sudo systemctl status eclipse-obd'` returns `active (running)`
- `ssh ... 'sudo journalctl -u eclipse-obd -n 20'` shows startup log lines
- `systemctl restart` survival (no data corruption to local SQLite)
- **Reboot survival** (CIO step regardless — physical Pi access)
- `install-service.sh` re-run idempotency verified against live Pi

## Also blocked by permissions

One `.claude/commands/review-stories-tuner.md:49` single-line edit (stale
`src/obd_config.json` → `config.json`) was **denied** by the Ralph harness
permission allowlist — `Edit(Z:/o/OBD2v2/.claude/commands/**)` is not in
`offices/ralph/.claude/settings.local.json`. This is not matched by the
US-179 acceptance grep (which looks for `src/main.py`, not `obd_config.json`)
so acceptance can still pass, but the exact TD-010 affected-file is still
stale. **Recommended**: operator runs the one-line sed from a normal shell,
or PM adds `Edit(Z:/o/OBD2v2/.claude/commands/**)` to Ralph's allow-list.

## Recommendation — operator verification recipe

After approving the `.claude/commands/` edit above (or letting the operator
handle it), run from a normal git-bash terminal in `Z:/o/OBD2v2`:

```bash
# 0. Precondition: US-176 live verification done
#    (chi-eclipse-01 hostname set, Projects/Eclipse-01 tree in place,
#     ~/obd2-venv exists and has requirements installed)
ssh mcornelison@10.27.27.28 'hostname'           # expect chi-eclipse-01
ssh mcornelison@10.27.27.28 'ls ~/Projects/Eclipse-01/src/pi/main.py'

# 1. Sync US-179 code to Pi
bash deploy/deploy-pi.sh

# 2. Install the service on the Pi (requires sudo on the Pi side)
ssh mcornelison@10.27.27.28 \
  'cd ~/Projects/Eclipse-01/deploy && sudo bash install-service.sh'

# 3. Start + verify
ssh mcornelison@10.27.27.28 'sudo systemctl start eclipse-obd && sleep 5'
ssh mcornelison@10.27.27.28 'sudo systemctl status eclipse-obd' # expect active (running)
ssh mcornelison@10.27.27.28 'sudo journalctl -u eclipse-obd -n 50'

# 4. Restart survival
ssh mcornelison@10.27.27.28 'sudo systemctl restart eclipse-obd && sleep 5 && sudo systemctl status eclipse-obd'
ssh mcornelison@10.27.27.28 \
  'sqlite3 ~/Projects/Eclipse-01/data/obd.db "PRAGMA integrity_check;"'   # expect ok

# 5. Idempotency — re-run install-service.sh (zero diff expected)
ssh mcornelison@10.27.27.28 \
  'cd ~/Projects/Eclipse-01/deploy && sudo bash install-service.sh'
ssh mcornelison@10.27.27.28 'sudo systemctl status eclipse-obd'         # still active

# 6. Reboot survival (CIO action — service comes up on its own)
ssh mcornelison@10.27.27.28 'sudo reboot'
# ... wait 60s ...
ssh mcornelison@10.27.27.28 'sudo systemctl status eclipse-obd'         # expect active
```

## Sprint contract status

US-179 is being marked `passes: false` in `sprint.json` per the strict
"partial completion = false" rule. The completion notes call out the
live-verification gap so the next session (or the operator) can close it
out. TD-010 will be marked complete once the `.claude/commands/` edit lands
and the operator confirms live install.

## Relation to TD-012

TD-012 (legacy `scripts/deploy*.sh` overlap) is partially closed by this
story:
- Makefile repointed from `scripts/deploy*.sh` to `deploy/deploy-pi.sh` ✓
- The old `scripts/deploy.sh`, `scripts/pi_setup.sh`, `scripts/deploy-env.sh`
  files are **not deleted** — that's the recommended option (a) but is out
  of US-179's scope. Suggested follow-up: small housekeeping PR that deletes
  them, or moves them under `scripts/legacy/`.
