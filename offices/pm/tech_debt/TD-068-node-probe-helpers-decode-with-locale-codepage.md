# TD-068 — the carousel node-probe test helpers decode stdout with the Windows locale codepage

- **Filed by:** Ralph (Rex), Sprint 63 (V0.29.17), during US-489.
- **Severity:** low (latent — no shipped code affected, no test currently wrong).
- **Type:** tech-debt / test-harness correctness.
- **Status:** OPEN. Fixed in the one file US-489 touched; the sibling helpers
  are unchanged (scope fence).

## The defect

Every pytest helper that shells out to `tests/ui/carousel_probe.js` builds the
subprocess like this:

```python
proc = subprocess.run([...], capture_output=True, text=True)
return json.loads(proc.stdout)
```

`text=True` **without `encoding=`** decodes the child's stdout using the
platform's *locale* encoding — cp1252 on this Windows dev host. `carousel.js`
and node both emit **UTF-8**. So any non-ASCII character in a rendered string
survives the round-trip mangled: the dashboard's `·` separator (U+00B7, UTF-8
`0xC2 0xB7`) is read back as the two characters `Â·`.

## Why it has not bitten yet

Nothing asserted on non-ASCII copy until now. US-489's summary line is the first
(`"SYSTEM · OK"`), and it failed with a one-character diff that looks exactly
like a bug in the production string — the misleading part. The production code
was correct the whole time; the harness was lying about what it read.

## Affected helpers (all identical, all latent)

| File | Helper |
|---|---|
| `tests/ui/test_carousel_idle_home.py` | `_view` |
| `tests/ui/test_carousel_honest_availability.py` | `_view` |
| `tests/ui/test_carousel_brightness.py` | (probe helper) |
| `tests/ui/test_carousel_letterbox_scale.py` | (probe helper) |
| `tests/ui/test_dashboard_stop_tier_safety.py` | `_probe` |

`tests/ui/test_carousel_system_summary.py::_view` is **already fixed** (US-489)
and carries a comment pointing here.

`tests/deploy/test_dashboard_kit.py` runs `node -e` with the same `text=True`
omission; same latent exposure.

## The fix

Add `encoding="utf-8"` to each `subprocess.run(...)` call. One argument per
helper, no behaviour change for the ASCII assertions that exist today.

Worth doing as one small mechanical story rather than piecemeal: the value of
the guard is that it is uniform, and a half-converted set of helpers is the
state in which someone re-debugs this from scratch.

## Why it was not fixed in US-489

Scope fence (refusal rule 3) — US-489 is a presentation-only story on the System
Status card. Fixing five unrelated test files inside it would have widened the
diff PM reviews for no in-sprint benefit, since every one of those assertions
passes today.
