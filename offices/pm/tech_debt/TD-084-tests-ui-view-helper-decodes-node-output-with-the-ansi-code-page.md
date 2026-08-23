# TD-084 — `tests/ui` `_view()` helper decodes the node probe with the Windows ANSI code page

**Filed by:** Rex (Ralph) during US-564
**Date:** 2026-08-21
**Severity:** Low (latent — no shipped code affected, but it silently weakens UI tests)
**Type:** Test-infrastructure defect

## What

Every `tests/ui/test_carousel_*.py` file copies the same helper:

```python
proc = subprocess.run([_NODE, _PROBE, fn, json.dumps(arg)], capture_output=True, text=True)
return json.loads(proc.stdout)
```

`text=True` decodes the child's stdout using **`locale.getpreferredencoding()`** — on this
Windows dev box, cp1252, not UTF-8. `carousel.js` renders real Unicode (`—` U+2014, `·`
U+00B7, `✓` U+2713), so any assertion on a rendered glyph compares against mojibake.

## How it surfaced

US-564 changed `syncTile` to render `— pending` instead of a fabricated `0 pending`.
The new assertion failed while pytest's own failure message *displayed* both sides as
looking identical — the classic shape where the test output actively misleads you about
why it failed. Cost ~15 minutes and two wrong hypotheses (file encoding, then source
encoding) before the actual cause was found.

## Why it has not bitten before

**No existing `tests/ui` assertion contains a non-ASCII character.** The helper has been
wrong since it was written and nothing has looked at the part of the output it corrupts.
That is the point worth recording: this is not a bug that appeared, it is a bug that was
finally *reached*.

## Blast radius

Every `tests/ui` file carrying its own copy of `_view()` (8+ at last count — see also
**TD-080**, which records the same duplicate-helper problem for `_fnBody`). Any future
UI test asserting on an em-dash, a middot, a check-glyph, a degree sign or a `·`
separator will fail confusingly, or — worse — a `not in` assertion will pass vacuously.

## Fix

Decode explicitly instead of relying on the locale:

```python
proc = subprocess.run([_NODE, _PROBE, fn, json.dumps(arg)], capture_output=True)
return json.loads(proc.stdout.decode("utf-8"))
```

`tests/ui/test_carousel_sync_pending_na.py` already does this and documents why.
The sweep is mechanical across the other copies — and the copies themselves are the
real debt (TD-080's lesson, second instance): one shared helper module for the node
probe would fix this class permanently rather than 8 times.

## Why it was not fixed in US-564

Scope fence. US-564 touches the sync tile; rewriting the probe helper in 8 unrelated UI
test files is a separate mechanical change that deserves its own diff and its own green
run, not a rider on a sensor-gate story.
