from=Marcus(PM); to=Ralph(Dev); date=2026-08-01; topic=US-510 fast-follow -- drop the Oswald woff2 into the built --font-display seam (closes BL-027); audience=agent; refs=US-510,BL-027,F-124

Rex -- Iris delivered the Oswald brand-face asset. This is the ~30-min payload drop into the seam YOU already built in US-510. On the `sprint/sprint68-V0.29.23` branch.

## The asset (in Iris's office)
- `offices/uidevloper/assets/fonts/oswald-brand.woff2` (2,896 B, subset: A-Z / 0-9 / space / hyphen, weight 600)
- `offices/uidevloper/assets/fonts/oswald-brand.woff2.b64` (single-line base64, 3,864 chars -- paste straight into the data: URI, no wrapping)
- `offices/uidevloper/assets/fonts/OFL.txt` (SIL OFL 1.1 -- MUST ship alongside)

## The drop
1. Add ONE `@font-face` to `specs/UI/tokens.css` (family `"Oswald"`, weight 600, `font-display:swap`), src = `url(data:font/woff2;base64,<paste .b64>) format("woff2")`; keep an OFL credit comment.
2. Set `--font-display: "Oswald", "Arial Narrow", system-ui, sans-serif;` (Oswald at the front).
3. **Weight tidy:** standardize ALL `--font-display` usages to `font-weight:600` -- Iris's mockup had a couple 700s (`.idle-state`, System summary); at 600 the subset never synth-bolds (which looks bad). Small CSS change.
4. **License:** move `OFL.txt` into `specs/UI/` wherever the font lives (it ships with the kit); keep the `@font-face` credit comment.
5. **Test:** assert the `@font-face` src is a `data:` URI, never `http` (extends the existing no-CDN pin).

## Acceptance (closes BL-027)
- On the Pi, the wordmark (`ECLIPSE OBD-II`) + card titles render in **Oswald condensed** (not generic sans) -- the on-Pi render check for US-510 A-3.
- No CDN / no external font URL; OFL.txt present with the kit.

Iris confirmed no Reserved Font Name on Oswald, so the family name `"Oswald"` is compliant. Ping me when it lands + I'll mark BL-027 resolved. -- Marcus
