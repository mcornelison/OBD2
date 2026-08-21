# TD-084 — The drill-down no-raw-colour guard reads comments and selectors as hex literals

**Filed by:** Ralph (Rex) — 2026-08-21, during US-558 (F-132)
**Severity:** low (loud false FAILURE, never a false pass)
**Location:** `tests/ui/test_carousel_system_drilldown.py::test_dashboardCss_drillDownOverlayCarriesNoRawColourLiteral`

## What it does today

```python
css = _read(_CSS)
start = css.index("#sys-detail")
block = css[start : start + 1800]
assert "#" not in block.replace("#sys-detail", "").replace("#sys-", "")
```

The guard's INTENT is right and worth keeping: every colour on the drill-down
overlay must be a `tokens.css` var, never a raw hex — the fork this project has
repeatedly paid for. But its subject is DECLARATIONS, and what it actually
inspects is 1800 raw characters, so it treats three different things as a colour
literal:

1. **CSS comments.** Any `#` in prose inside the window fails it.
2. **Selectors** — already visible in the code as two `.replace()` patches
   (`#sys-detail`, `#sys-`), which is the guard fighting this exact conflation.
3. **A fixed 1800-char window**, so the region it polices drifts whenever
   anything above or inside the overlay's rules grows or shrinks.

## How it surfaced

US-558 added a comment to `#sys-detail` cross-referencing where the overlay
opacity rule is declared (`#setup-menu`). The guard went red on a comment. The
US-558 change itself was the *removal* of a raw literal — `rgba(0,0,0,0.95)` →
`var(--bg)` — so the guard failed on a commit that moved its own metric in the
right direction.

## Why this is low severity, and not zero

It fails LOUD and in the safe direction: it can never pass a real raw hex. The
cost is that it blocks a legitimate edit and pushes the author toward a workaround
rather than a fix. US-558 took the workaround under the scope fence — the comment
now spells the cross-reference without its `#`, with a note saying why — which
means the sheet now carries an oddity whose only justification is a test's
crudeness. That is the debt.

## Suggested fix (small)

Strip comments before the scan (there is already a `_stripJsComments` helper in
the same module — the CSS side wants the equivalent), and match hex by the shape
of a colour (`#[0-9a-fA-F]{3,8}` at a value position) rather than by the bare `#`
character. That drops both `.replace()` patches as a side effect. A regex over
`(?<![-\w])#[0-9a-fA-F]{3,8}\b` inside declaration values covers it.

While there: consider ending the window at the last rule that belongs to the
overlay rather than at a fixed offset — a character count is a measurement of the
file, not of the subject.

`tests/ui/test_overlay_opacity_model.py` (US-558) has a `_stripComments` helper
that can be lifted directly; that module also pins WHY it exists — an
un-stripped comment contains no braces, so it reads as part of the next rule's
selector and that rule silently drops out of a discovery walk.

## Not in scope for US-558

`tests/ui/test_carousel_system_drilldown.py` is US-509's guard. US-558's scope
fence is the overlay opacity rule; rewriting a neighbouring story's assertion to
unblock my own comment is precisely the drift the fence exists to stop.
