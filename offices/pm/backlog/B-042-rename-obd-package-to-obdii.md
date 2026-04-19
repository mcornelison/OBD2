# B-042: Rename `src/pi/obd/` → `src/pi/obdii/` (resolve I-014 name collision)

**Priority**: High (gates real OBD-II connection on Pi)
**Size**: M (mechanical; wide touchpoint but predictable)
**Status**: **RESOLVED** (US-187 Sprint 12 Session 53 — rename shipped on `sprint/pi-polish`)
**Epic**: E-11 (Infrastructure Pipeline)
**Related**: I-014 (also Resolved), B-037 (Sprint 10–13 Pi work — Run phase gated by this)
**Filed**: 2026-04-17 (PM Session 20)
**Resolved**: 2026-04-18 (Sprint 12 US-187, Rex Session 53)

## Resolution Note

Rename completed via `git mv src/pi/obd src/pi/obdii` + bulk import rewrite
across `src/`, `tests/`, `scripts/`, `offices/ralph/` Python files (~90 files)
plus canonical doc updates in `specs/architecture.md`, `offices/ralph/agent.md`,
`offices/ralph/knowledge/codebase-architecture.md`, `src/README.md`, and the
renamed `src/pi/obdii/` package READMEs. Zero regressions on Windows fast-suite
(2068 tests) + Pi smoke test (`python -c 'import obd; print(obd.OBD)'` now
resolves to the third-party python-OBD library). Historical mentions in
`offices/pm/` inbox notes, blocker/tech-debt docs, and PM session logs
intentionally preserved as-written — they reference the pre-rename state
accurately.

## Summary

Rename the project's `src/pi/obd/` package to a non-colliding name so
`import obd` in third-party-library call sites (e.g., `obd.OBD(...)` from
python-OBD) resolves to the correct package.

**Chosen name**: `obdii` — unambiguous, industry-standard spec name, short,
readable.

## Motivation

I-014 documents the collision. Real OBD-II connections on the Pi fail
because our `obd` package shadows the third-party library at runtime
under systemd. Sprint 10 crawl phase is unblocked (simulator-only), but
Sprint 11+ Run phase requires this fix.

## Scope

Estimate: ~45 files in `src/pi/obd/`, plus all imports across `src/`,
`tests/`, `scripts/`, and any doc strings / spec references.

### Mechanical steps
1. `git mv src/pi/obd/ src/pi/obdii/`
2. Global search-replace on imports:
   - `from pi.obd.` → `from pi.obdii.`
   - `import pi.obd.` → `import pi.obdii.`
   - `from src.pi.obd.` → `from src.pi.obdii.` (rare — `src.pi.*` is the
     stale form that TD-014 also addresses)
3. Update `src/pi/obd/__init__.py` re-exports if they reference package
   path by name.
4. Update any `@pytest.fixture` paths, conftest references.
5. Update spec references: `specs/architecture.md`, `specs/standards.md`
   anywhere mentioning `src/pi/obd/`.
6. Update PM/Ralph docs: `offices/ralph/agent.md`, `CLAUDE.md`.
7. Verify by: `pytest tests/` green + `grep -r 'pi\.obd\b' src/` returns
   zero hits.
8. Live-verify on Pi: `sudo systemctl start eclipse-obd` connects to a
   real dongle (need CIO BT-paired OBDLink LX) OR at minimum `python -c "import obd; print(obd.OBD)"` succeeds in the Pi venv.

### Invariants
- No behavioral changes — purely structural rename.
- Existing test count (~1923 on Windows, ~X on Pi) must stay equal-or-higher.
- Ruff clean throughout.
- Zero `from src.pi.*` imports land — TD-014 should land in the same PR
  or be already fixed before this starts.

## Open grooming questions

1. **Commit strategy**: one giant rename commit, or staged (rename dirs,
   then sweep imports, then sweep docs)? Recommend: one commit, because
   tools (ruff, pytest) are atomic gates — half-renamed is broken.
2. **Sprint placement**: Sprint 11 (ahead of Run phase)? Parallel to
   walk-phase work? Depends on CIO BT-pairing timeline.
3. **Coordinate with TD-014 fix**: TD-014 changes `from src.pi.hardware.*`
   to `from pi.hardware.*`. Should land BEFORE or WITH B-042 so we don't
   ship a half-reorganized import tree.

## Acceptance criteria (to be written when B-042 enters a sprint)

- All imports post-rename use `pi.obdii.*` form (never `pi.obd.*`)
- `import obd` in Python resolves to python-OBD library (verified on Pi)
- `obd.OBD(...)` constructs successfully on Pi (venv import test)
- Full test suite green on Windows + Pi
- Ruff clean
- No regressions to simulator, display, alerts, analytics, or sync paths
- Documentation refreshed: architecture.md, standards.md, agent.md mention
  the new package name
- CIO smoke test: `sudo systemctl start eclipse-obd` on the Pi reaches
  the OBD connection retry logic without the `has no attribute 'OBD'`
  error (actual connection still requires BT-paired dongle — out of
  scope for this story)

## Risks

- **Import churn across tests**: many test files import from `pi.obd.*`.
  Rename is mechanical but the blast radius is wide.
- **Conflicts with in-flight work**: if Ralph is working another story
  that edits `src/pi/obd/*`, the rename PR conflicts. Sequence B-042 when
  no other sprint is touching that subtree.
- **Late surprises**: a callsite may reference `obd` via string (e.g.,
  `importlib.import_module("obd")`) — grep for string literals too.
