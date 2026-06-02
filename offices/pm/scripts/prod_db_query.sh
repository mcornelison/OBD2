#!/usr/bin/env bash
################################################################################
# File Name: prod_db_query.sh
# Purpose/Description: Run a SQL statement against the chi-srv-01 production
#   `obd2db` via the app's own async engine, so the MariaDB password never
#   leaves the server (read from server-side .env DATABASE_URL). PM/ops tool —
#   replaces the ad-hoc `ssh ... 'bash -s' <<heredoc` blocks scattered through
#   deploy/validation sessions. SELECTs print tab-separated rows to stdout +
#   a "(N rows)" line to stderr; DDL/DML print "OK (N affected)".
# Author: Marcus (PM)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Usage:
#   bash offices/pm/scripts/prod_db_query.sh "SELECT id, ecu_signature FROM ecu ORDER BY id;"
#   bash offices/pm/scripts/prod_db_query.sh --file path/to/query.sql
#   PROD_DB_HOST=user@host bash offices/pm/scripts/prod_db_query.sh "SELECT 1;"
#
# Safety: pass any SQL; it runs as the app DB user (read+write). Prefer SELECT
#   for inspection. The SQL travels via an env var (no shell/quote injection
#   into the Python source — Python reads it from os.environ).
################################################################################
set -euo pipefail

HOST="${PROD_DB_HOST:-mcornelison@chi-srv-01}"
PROJECT="${PROD_DB_PROJECT:-/mnt/projects/O/OBD2v2}"
VENV="${PROD_DB_VENV:-/home/mcornelison/obd2-server-venv}"

if [[ "${1:-}" == "--file" ]]; then
  [[ -n "${2:-}" && -f "$2" ]] || { echo "usage: prod_db_query.sh --file <path.sql>" >&2; exit 2; }
  SQL="$(cat "$2")"
else
  SQL="${1:?usage: prod_db_query.sh \"<SQL>\"   (or --file <path.sql>)}"
fi

# Ship SQL as a shell-safe env var; the remote Python reads it from os.environ
# so no SQL text is interpolated into the Python source.
ssh "$HOST" "export OBD_SQL=$(printf %q "$SQL") OBD_PROJECT=$(printf %q "$PROJECT") OBD_VENV=$(printf %q "$VENV"); bash -s" <<'REMOTE'
set -euo pipefail
cd "$OBD_PROJECT"
set -a; . ./.env 2>/dev/null || true; set +a
PYTHONPATH="$OBD_PROJECT" "$OBD_VENV/bin/python" - <<'PY'
import os, sys, asyncio
from sqlalchemy import text
from src.server.db.connection import createAsyncEngine

async def main():
    eng = createAsyncEngine(os.environ["DATABASE_URL"])
    try:
        async with eng.connect() as c:
            res = await c.execute(text(os.environ["OBD_SQL"]))
            if res.returns_rows:
                rows = res.all()
                for r in rows:
                    print("\t".join("NULL" if v is None else str(v) for v in r))
                print(f"({len(rows)} rows)", file=sys.stderr)
            else:
                await c.commit()
                print(f"OK ({res.rowcount} rows affected)", file=sys.stderr)
    finally:
        await eng.dispose()

asyncio.run(main())
PY
REMOTE
