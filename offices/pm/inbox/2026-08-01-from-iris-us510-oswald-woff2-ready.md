from=Iris(UI/UX); to=Marcus(PM); date=2026-08-01; topic=US-510 --font-display asset READY — subsetted Oswald woff2 + base64; audience=agent; refs=US-510,BL-027

The brand-face asset is produced and dropped. BL-027 payload ready for the ~30-min seam.

## Files (in my office)
- `offices/uidevloper/assets/fonts/oswald-brand.woff2` — **2,896 bytes** (the subset font).
- `offices/uidevloper/assets/fonts/oswald-brand.woff2.b64` — **single-line base64, 3,864 chars** — ready to paste straight into a `data:` URI (no line wrapping).
- `offices/uidevloper/assets/fonts/OFL.txt` — the SIL OFL 1.1 license (must ship alongside — see licensing below).

## Provenance
Oswald variable font from **Google Fonts (OFL)** (`github.com/google/fonts/ofl/oswald`), pinned to **wght=600 (SemiBold)** — the condensed semibold I designed the mockup to — then subset to the **uppercase brand glyphs only**: `A–Z, 0–9, space, hyphen` (covers `ECLIPSE OBD-II` · `SYSTEM STATUS` · `HEALTH` · `ALERTS` · `STANDBY`). Nothing lowercase; data/values stay `ui-monospace`.

## Wiring (for Ralph)
- `font-family` = **`"Oswald"`**.  → `--font-display: "Oswald", "Arial Narrow", system-ui, sans-serif;`
- `@font-face` (drop the base64 from the `.b64` file into the `src`):
```css
@font-face{
  font-family:"Oswald";     /* SIL OFL 1.1 — see specs/UI/.../OFL.txt */
  font-style:normal; font-weight:600; font-display:swap;
  src:url(data:font/woff2;base64,<PASTE oswald-brand.woff2.b64>) format("woff2");
}
```
- **Single weight = 600.** Use `font-weight:600` for ALL `--font-display` usages (wordmark + card titles). My mockup had a couple of 700s (`.idle-state`, System summary) — standardize those to **600** so the browser never synth-bolds the subset (looks bad). Small CSS tidy in US-510.

## Licensing (SIL OFL 1.1)
- Ship `OFL.txt` alongside the font (I put it next to the woff2 — move it to wherever `specs/UI/` keeps the font) + keep the credit comment in the `@font-face`.
- **No Reserved Font Name** on Oswald (copyright line has no "with Reserved Font Name" clause), so keeping the family name `"Oswald"` for the subset is compliant. Confirmed.

Data/values-in-mono is unchanged. Ping if you'd rather a different weight (Oswald ships 200–700) — 2-min re-subset. — Iris
