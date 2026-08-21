# TD-086 — `config.json` carries double-encoded mojibake, and tests read it locale-decoded

**Filed by:** Rex (Ralph) during US-564
**Date:** 2026-08-21
**Severity:** Medium (18 tests currently ERROR on a clean Windows checkout; corrupt data ships in `config.json`)
**Type:** Data corruption + test-infrastructure defect (two distinct bugs, same encounter)

## What

`pytest tests/pi/obdii/test_poll_set_expansion.py` produces **18 setup ERRORs** on a clean
checkout of `HEAD`:

```
tests/pi/obdii/test_poll_set_expansion.py:46: in pollingConfig
    fullConfig = json.load(f)
...
E   UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position 6969
```

**This is pre-existing and unrelated to US-564.** Verified rather than assumed:
`git status --porcelain config.json` and `... test_poll_set_expansion.py` are both **empty**
— neither file differs from `HEAD`, so this reproduces on a fresh clone with no local work.

## Two separate defects

### 1. `config.json` contains double-encoded mojibake (the real one)

At byte offset ~6969:

```json
"description": "Safety-critical â€” every cycle (~1 Hz)",
```

The raw bytes are `C3 A2 E2 82 AC E2 80 9D` — that is `â`, `€`, `”`. The intended character
was a single em-dash `—` (U+2014, UTF-8 `E2 80 94`). What happened is the classic
**double-encode**: the file was read as cp1252, the em-dash decoded to the three mojibake
characters, and the result was written back out as UTF-8. The corruption is now *in the
committed bytes*, not an artifact of how it is displayed.

`config.json` is the project's SSOT config file, so this is corrupt shipped data, not just
an ugly string. Worth grepping the whole file (and `.env.example`, `config.example.json`)
for other non-ASCII sequences from the same event.

### 2. The test decodes it with the locale code page

`test_poll_set_expansion.py:46` opens the file without an explicit encoding, so Python uses
`locale.getpreferredencoding()` → **cp1252** on this Windows dev box. `0x9D` is undefined in
cp1252, so it raises. Even once defect 1 is fixed, a legitimate non-ASCII character anywhere
in `config.json` would break this test again on Windows.

## Why the two must be fixed together

Fixing only the encoding makes the tests pass **while the mojibake stays in the config** —
the tests would then happily assert against corrupt data. Fixing only the mojibake leaves
the next non-ASCII character to break the suite. This is the same shape as US-564's own
two-layer `syncPending` rule: either half alone ships green and leaves the defect in place.

## Fix

1. Repair the string in `config.json` (`â€”` → `—`, plus any siblings from the same event).
2. Open it explicitly: `open(path, encoding="utf-8")` at `test_poll_set_expansion.py:46`,
   and sweep `tests/` for other `json.load(open(...))` / `open(...)` calls on repo data
   files that omit `encoding=`.

## Related — this is now the THIRD instance of one root cause

- **TD-084** — `tests/ui` `_view()` decodes the node probe with the ANSI code page (`text=True`).
- **TD-080** — the duplicated `_fnBody` helper (same "N copies, fix it N times" shape).
- **This one** — `config.json` read with the locale code page.

The generalisation worth acting on: **on Windows, any `open()` / `subprocess(text=True)`
without an explicit `encoding=` is a latent locale-dependent defect.** It stays invisible
exactly as long as the data stays ASCII, then surfaces confusingly the first time it does
not — TD-084 cost ~15 minutes and two wrong hypotheses for precisely this reason. A ruff
rule would catch the class permanently: **`PLW1514`** (`unspecified-encoding`) or
flake8-executable's equivalent, enabled in `pyproject.toml`.

## Why it was not fixed in US-564

Scope fence. US-564 is the sensor plausibility gate; it touches neither `config.json` nor
the OBD poll-set tests. Repairing shipped config data and sweeping encoding calls across
`tests/` deserves its own diff and its own green run.
