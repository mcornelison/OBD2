---
name: pattern-brand-font-subset-woff2-inline
description: How to produce a tiny CSP-safe inline brand font for the kiosk — download an OFL font, pin the weight, subset to the exact glyphs, emit woff2 + base64 for an @font-face data-URI. The kiosk CSP blocks font CDNs, so this is the ONLY way to ship a display face.
metadata:
  type: pattern
---

# Brand display font → subsetted woff2 + base64 (CSP-safe inline @font-face)

The Pi kiosk (and Artifacts) **block external font CDNs** — a webfont must be **inlined** as an
`@font-face` `data:` URI. Ship only the glyphs actually used, so the payload stays tiny.
Did this for US-510 `--font-display` (Oswald) 2026-08-01 → a **2,896-byte** woff2.

## Recipe (Windows / git-bash, fonttools already present)
```bash
python -m pip install brotli            # REQUIRED for woff2 (fonttools won't emit woff2 without it)
# 1. grab an OFL (redistributable) font — Google Fonts repo ships the variable TTF:
curl -fsSL "https://raw.githubusercontent.com/google/fonts/main/ofl/<fam>/<Family>%5Bwght%5D.ttf" -o VF.ttf
# 2. pin the weight you designed to (VF -> static instance = smaller):
python -m fontTools.varLib.instancer VF.ttf wght=600 -o Pinned.ttf --quiet
# 3. subset to ONLY the glyphs used. Uppercase brand moments = A-Z 0-9 space hyphen:
pyftsubset Pinned.ttf --unicodes=U+0041-005A,U+0030-0039,U+0020,U+002D --flavor=woff2 --output-file=brand.woff2
# 4. single-line base64 for the data URI (NO -w wrapping):
base64 -w0 brand.woff2 > brand.woff2.b64
# family name (for the @font-face + --font-display front):
python -c "from fontTools.ttLib import TTFont; print(TTFont('brand.woff2')['name'].getDebugName(1))"
```
`@font-face{ font-family:"<Fam>"; font-weight:600; font-display:swap;
  src:url(data:font/woff2;base64,<paste .b64>) format("woff2"); }`

## Gotchas
- **brotli** is the usual missing piece — woff2 = brotli-compressed; install it first.
- **Match the CSS to the single subset weight.** One weight in the file → use that `font-weight`
  everywhere; a different weight (e.g. 700) triggers ugly **synthetic bold** on a subset.
- **Subset only what renders in the face.** Data/values stay `ui-monospace`, so mono-only chars
  (`·`, `⋮`, lowercase) are NOT in the display subset — keeps it tiny.
- **License must travel with it.** SIL OFL 1.1 → ship `OFL.txt` alongside + a credit comment. Check
  the copyright line for **"with Reserved Font Name"** — if present, you must **rename** the family
  for a subset/modified build; if absent (Oswald's case), keeping the name is fine.
- The actual @font-face lands in `specs/UI/tokens.css` (Ralph's build); I produce the asset + base64
  + wiring and hand it over. Pairs with [[pattern-ui-as-ssot-consumer]] (`--font-display` is a token).
