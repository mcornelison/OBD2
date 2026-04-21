# Hygiene Issue — benchtest code paths incorrectly tag rows as `data_source='real'`

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (latent data-pollution bug; file as standalone story)

## Why I'm filing this standalone

Ralph's US-205 dry-run (`offices/tuner/inbox/2026-04-20-from-ralph-us205-halt.md`) surfaced that the Pi has **352,508 rows** tagged `data_source='real'` — ~352,400 of which are post-Sprint-14 benchtest runs, NOT live-vehicle captures.

I referenced this bug as Amendment 3 in my US-205 amendment note (`2026-04-20-from-spool-us205-amendment.md`), but the root cause is separate from the Session 23 truncate — it deserves its own story so it doesn't get absorbed into US-205 or lost. US-205 is a ONE-TIME cleanup; without this fix, the same problem recurs as soon as the next benchtest runs.

## The bug

US-195 added `data_source TEXT NOT NULL DEFAULT 'real' CHECK (data_source IN ('real','replay','physics_sim','fixture'))` to capture tables (`realtime_data`, `connection_log`, `statistics`, etc.).

**The `DEFAULT 'real'` is the problem.** It was intended as a safety net for the live-OBD writer path so Ralph wouldn't have to touch every insert site during US-195 migration. But it means **any writer that doesn't explicitly pass a data_source value** — including benchtest, simulator, or dev-harness code paths — gets tagged `'real'` by default.

Result: the `data_source` column stops being a useful filter. Benchtest rows and true live-capture rows become indistinguishable in the operational store.

## Why it matters (tuning lens)

From `specs/architecture.md` §5 line 577 — the canonical filter rule for tuning-domain analytics:

> *"Server-side analytics, AI prompt inputs, and baseline calibrations MUST filter `WHERE data_source = 'real'` unless the caller is running a synthetic test."*

That rule only works if `'real'` truly means "captured from the real vehicle." Right now, 99.96% of rows tagged `'real'` are benchtest output. So:

- **Analytics**: any drive-keyed or parameter-trend query picks up benchtest rows as real-vehicle data. Baseline calibrations derived from this data are contaminated.
- **AI prompts**: the user_message.jinja template feeds `data_source='real'` rows as the "real vehicle driving data" the model reasons over. Right now it's reasoning over benchtest noise.
- **Tuning interpretation**: if Session 23's warm-idle fingerprint (RPM 761-852, LTFT 0.00%, coolant 73-74°C) gets averaged with benchtest rows pulled from a physics sim that generates different distributions, my "This Car's Empirical Baseline" section in `offices/tuner/knowledge.md` loses its grounding.

This is the exact scenario the `data_source` column was supposed to prevent. The bug defeats its purpose.

## Scope (suggested story skeleton)

```
Title: Benchtest code paths explicitly tag data_source — audit + fix + regression
Size: S
Priority: medium — should land before next benchtest run after US-205 truncate
Dependencies: US-205 (cleanup happens first so audit doesn't fight existing 352K rows)

Intent:
  Every INSERT into a capture table from a non-live-OBD code path MUST pass data_source
  explicitly as 'physics_sim' | 'replay' | 'fixture'. The DEFAULT 'real' becomes a
  narrow safety net for the single live-OBD writer, not a catchall.

Acceptance:
  1. Audit every INSERT into capture tables (realtime_data, connection_log, statistics,
     alert_log, and post-US-204/206 dtc_log + drive_summary). Produce file:line list of
     benchtest/sim/replay call sites.
  2. Each non-live-OBD call site passes data_source explicitly:
     - Pure physics sim → 'physics_sim'
     - Replay from fixture/file → 'replay'
     - Regression fixture seeder → 'fixture'
     - Test harnesses that write to operational DB (ideally should use a test DB
       instead, but if they don't, tag appropriately)
  3. Live-OBD writer (src/pi/obdii/data/helpers.py::logReading and peers) keeps
     implicit DEFAULT 'real' — that's correct.
  4. New test: INSERT without data_source from non-live path → ruff/mypy/lint fails
     OR a runtime assertion catches it. (Ralph picks the enforcement mechanism.)
  5. Regression: grep confirms no capture-table INSERT in non-live paths lacks
     an explicit data_source.
  6. specs/architecture.md §5 line 577 language tightened:
     "Writers outside the live-OBD path MUST pass data_source explicitly; DEFAULT
     'real' is a narrow safety net for the single live-OBD collector, not a
     catchall for dev writers."

Stop conditions:
  - STOP if audit finds capture-table writers in code paths Spool/CIO didn't know
    existed (e.g. hidden dev tool, debug script) — surface in inbox note before
    deciding how to tag.
  - STOP if it turns out some benchtest rows SHOULD be tagged 'real' (e.g., an
    OBDLink-to-bench-ECU setup that's actually reading real sensor data just not
    from the Eclipse) — rare but possible, clarify before tagging.

Invariants:
  - DEFAULT 'real' stays in schema — do NOT change the column default. Fix is at
    call sites, not schema.
  - CHECK constraint stays — all four enum values remain valid.
  - No data migration (US-205 already truncated; new writes land correctly).
```

## Why small (S-size) and why before next benchtest

- The audit is grep-scale work: find every INSERT into capture tables, classify call sites.
- Most call sites are probably 1-3 functions (one physics sim entry point, maybe one replay entry point, one live-OBD entry point).
- The fix is adding explicit arguments at each site + one line of schema doc tightening.
- Test pass is straightforward.

And the timing: if CIO runs a benchtest between US-205 cleanup and this hygiene story landing, we're right back where we started — 352K fresh benchtest rows tagged `'real'`, and the next truncate is the only way out. Get this in before the next benchtest run and the problem doesn't recur.

## Not my lane, but offering for context

Ralph probably knows exactly which code paths are the benchtest writers — a 5-minute grep will answer it. If the audit comes back with something unexpected (e.g., a dev tool I didn't know about writes real-tagged rows), that's worth an inbox back to me before deciding how to tag.

## Sources

- US-205 halt note: `offices/tuner/inbox/2026-04-20-from-ralph-us205-halt.md` (where the 352K number surfaced)
- US-205 amendment: `offices/pm/inbox/2026-04-20-from-spool-us205-amendment.md` (Amendment 3 is the short version of this note)
- data_source contract: `specs/architecture.md` §5 "Data Source Column (US-195)" line 568-579
- data_source column source: `src/pi/obdii/data_source.py::CAPTURE_TABLES`

— Spool
