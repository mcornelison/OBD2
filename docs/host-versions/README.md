# Host versions — what is actually installed on the Pi and the server

**Why this folder exists.** The `requirements*.txt` files are `>=` floors. They say what
is *allowed*, not what *runs*. On 2026-09-14, **ARCH-026** (CIO override, applied by Atlas)
upgraded 12 pip packages plus the Python 3.13 and SQLite security point releases on the Pi,
and 10 pip packages on the server, directly on the hosts. Nothing in the repo recorded it.
A reflashed Pi or a rebuilt server would have installed whatever PyPI served that day.

These files are the durable, versioned record of those hosts. They were **measured, not
transcribed**: captured read-only over SSH on **2026-09-17** (`pip freeze` from each production
venv, `dpkg-query` on the Pi) and checked against the ARCH-026 card. All 22 upgraded packages
matched, and nothing had changed since 2026-09-14.

| File | Host / venv | What it is |
|---|---|---|
| `pi-obd2-venv.freeze.txt` | `chi-eclipse-01` `/home/mcornelison/obd2-venv` (Python 3.13.5) | Current, after ARCH-026 |
| `pi-obd2-venv.before-ARCH-026-20260914.freeze.txt` | same | Rollback point (copy of the host's own pre-change freeze) |
| `pi-apt-python-sqlite.txt` | `chi-eclipse-01` apt | python3.13 family `deb13u5`, sqlite3 `deb13u2` |
| `server-obd2-server-venv.freeze.txt` | `chi-srv-01` `~/obd2-server-venv` | Current, after ARCH-026 |
| `server-obd2-server-venv.before-ARCH-026-20260914.freeze.txt` | same | Rollback point |

## Using them

- **Rebuild to the running state:** `pip install -r docs/host-versions/<host>.freeze.txt`
  inside the target venv. (These files are deliberately NOT named `requirements*.txt`: the
  deploy scripts and the migration-drift CI key on that name.)
- **Roll back ARCH-026:** `pip install -r <host>.before-ARCH-026-20260914.freeze.txt`, then
  restart the service.

## Held on purpose, and not upgraded by ARCH-026

Pint under `obd`; the fastapi / starlette / uvicorn / websockets group; raspi-firmware;
mypy 2.x and ruff 0.16. The reasons are on the ARCH-026 card.

## Keeping this true

Anyone who changes a package on either host refreshes the matching `*.freeze.txt` here, in the
same session. The human-readable ledger with reasons is
`$FLEET_SHARE/_shared/knowledge/library-version-history.md`. That file is on the share, which has
no git and no snapshots. **This folder is the copy that cannot be lost.**

Still owed, and tracked as a backlog story, not done here: real pins in the `requirements*.txt`
files, and moving dev tools (pytest, ruff, mypy, black) out of the production installs.
