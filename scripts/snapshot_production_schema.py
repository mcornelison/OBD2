#!/usr/bin/env python3
################################################################################
# File Name: snapshot_production_schema.py
# Purpose/Description: US-807 -- regenerate tests/server/_production_schema_snapshot.py
#   from the DEPLOYED server database: SHOW CREATE TABLE for every base table,
#   plus production's own migration ledger. READ-ONLY against production.
#
# WHY THIS EXISTS -- the A-4 applied-schema gate was comparing the models to
#   themselves. It provisioned MariaDB with create_all and then checked the
#   result against the same models, so it could never see BL-019: a model
#   column added with no migration to put it on the deployed database. CIO
#   ruling 2026-10-06: build the CI database from production's REAL schema,
#   stamp production's ledger, run every newer migration forward, then compare.
#   A model change without a migration is then red on the PR that makes it.
#
# WHEN TO RE-RUN
#   Not on a schedule. A stale snapshot is still correct -- the CI runs every
#   migration newer than the pinned ledger forward, which is exactly what a
#   deploy does. Refresh after a deploy that changed the server schema, so the
#   pin stays close to what is deployed and the forward run stays short.
#
# Usage (from the repo root; needs ssh to the server, like prod_db_query.sh):
#   python -m scripts.snapshot_production_schema
#
# Author: Atlas (Architect) -- US-807, CIO-directed build
# Creation Date: 2026-10-06
################################################################################

"""Pin the deployed server schema for the A-4 applied-schema parity gate."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUERY_TOOL = REPO_ROOT / 'tools' / 'pm' / 'prod_db_query.sh'
SNAPSHOT_PATH = REPO_ROOT / 'tests' / 'server' / '_production_schema_snapshot.py'
LEDGER_TABLE = 'schema_migrations'

# The table-option counter, not the column attribute: `AUTO_INCREMENT=4102148`
# is how many rows production holds, which is state, not schema.
_AUTO_INCREMENT_OPTION = re.compile(r' AUTO_INCREMENT=\d+')


def sanitizeCreateTable(ddl: str) -> str:
    """Drop the row counter from a SHOW CREATE TABLE result; keep the rest byte-identical."""
    return _AUTO_INCREMENT_OPTION.sub('', ddl)


def parseShowCreate(stdout: str, tableName: str) -> str:
    """Return the DDL from one ``SHOW CREATE TABLE`` row (``name<TAB>ddl``).

    Raises:
        ValueError: when the output is empty or names a different table -- a
            snapshot must never pin a table it did not read.
    """
    name, sep, ddl = stdout.partition('\t')
    if not sep or name != tableName:
        raise ValueError(
            f'expected SHOW CREATE TABLE for {tableName}, got {stdout[:80]!r}',
        )
    return ddl.rstrip('\n')


def _literal(ddl: str) -> str:
    """A readable triple-quoted literal when it is safe, ``repr`` otherwise."""
    if '\\' in ddl or "'''" in ddl or ddl.endswith("'"):
        return repr(ddl)
    return "'''" + ddl + "'''"


def renderSnapshotModule(
    *,
    tables: Mapping[str, str],
    ledger: Iterable[str],
    measuredAt: str,
    serverVersion: str,
    database: str,
) -> str:
    """Render the snapshot module's source: sorted tables, sorted ledger."""
    lines = [
        '################################################################################',
        '# File Name: _production_schema_snapshot.py',
        '# Purpose/Description: US-807 -- GENERATED. The deployed server schema, read',
        '#   from production by scripts/snapshot_production_schema.py. Do not hand-edit:',
        '#   re-run the script. The A-4 applied-schema parity gate builds its CI database',
        '#   from this, stamps the ledger, then runs every newer migration forward.',
        '################################################################################',
        '',
        '"""Production server schema, pinned (GENERATED -- re-run the script, never edit)."""',
        '',
        'from __future__ import annotations',
        '',
        f'DATABASE: str = {database!r}',
        f'SERVER_VERSION: str = {serverVersion!r}',
        f'MEASURED_AT: str = {measuredAt!r}',
        '',
        '# The migrations production had applied when this was read, in order.',
        'PRODUCTION_LEDGER: tuple[str, ...] = (',
        *(f'    {version!r},' for version in sorted(ledger)),
        ')',
        '',
        '# SHOW CREATE TABLE for every base table except the ledger (the harness',
        '# rebuilds that), with the AUTO_INCREMENT row counter removed.',
        'PRODUCTION_TABLE_DDL: dict[str, str] = {',
    ]
    for name in sorted(tables):
        lines.append(f'    {name!r}: {_literal(tables[name])},')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def _runQuery(sql: str) -> str:
    """Run one read-only statement through the PM's production query tool."""
    result = subprocess.run(  # noqa: S603 -- argv is an explicit list
        ['bash', str(QUERY_TOOL), sql],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        cwd=REPO_ROOT,
    )
    return result.stdout


def readProduction(runQuery: Callable[[str], str] = _runQuery) -> dict[str, object]:
    """Read everything the snapshot needs from production (SELECT/SHOW only)."""
    database, serverVersion = runQuery('SELECT DATABASE(), VERSION()').strip().split('\t')
    names = runQuery(
        'SELECT TABLE_NAME FROM information_schema.TABLES '
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
        'ORDER BY TABLE_NAME',
    ).split()
    tables = {
        name: sanitizeCreateTable(parseShowCreate(runQuery(f'SHOW CREATE TABLE `{name}`'), name))
        for name in names
        if name != LEDGER_TABLE
    }
    ledger = runQuery(f'SELECT version FROM {LEDGER_TABLE} ORDER BY version').split()
    if not tables or not ledger:
        raise ValueError('production returned no tables or no ledger; refusing to pin nothing')
    return {
        'tables': tables,
        'ledger': ledger,
        'serverVersion': serverVersion,
        'database': database,
        'measuredAt': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def main() -> int:
    """Read production and rewrite the snapshot module (temp file, then replace)."""
    source = renderSnapshotModule(**readProduction())  # type: ignore[arg-type]
    temp = SNAPSHOT_PATH.with_suffix('.py.tmp')
    temp.write_text(source, encoding='utf-8', newline='\n')
    temp.replace(SNAPSHOT_PATH)
    print(f'wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
