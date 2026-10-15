# Michroma subset: provenance

**Cut by:** Iris (UI/UX), 2026-10-14, for US-887 (the V0.30 visual style). Ralph embeds this file; he does not need the source font or fontTools.

| | |
|---|---|
| File | `michroma-brand.woff2`, **2,464 B**, md5 `b495a16b2b5cf974f15e52d62e914d14` |
| Source | `https://raw.githubusercontent.com/google/fonts/main/ofl/michroma/Michroma-Regular.ttf` (64,344 B, sha256 `b62301163788bc5b7f8fcac0b74b184e34e1827e577b499ecb724da065098f87`), name ID 5 = `Version 1.100` |
| Weight | 400 only (Michroma has one weight). Never synthesise bold: `font-synthesis: none` |
| Glyphs | 38: `A–Z`, `0–9`, space, hyphen (the same set as `oswald-brand.woff2`) |
| Tool | fontTools 4.63.0 (`pyftsubset` API), script `michroma-cut.py` beside this file |
| Options | woff2 · no layout features (so no kerning) · no hinting · desubroutinised · name IDs 0–6 kept (copyright stays in the file) · no .notdef outline · DSIG dropped |
| Reproducible | `SOURCE_DATE_EPOCH=1760400000 python -P michroma-cut.py Michroma-Regular.ttf <outdir>` gives the same md5 on every run. Without the fixed epoch the `head.modified` stamp changes, the md5 changes, and the size can differ by a few bytes. My earlier figure of 2,468 B was cut without it. |
| Licence | SIL OFL 1.1, text in `OFL-michroma.txt`. **No Reserved Font Name**, so the family name `Michroma` may be kept for this subset. |
| Advances | `michroma-advances.json`: the advance width of each of the 38 characters in em (hmtx / unitsPerEm 2048), read from the source and checked equal in the subset. The width in px is `sum(advanceEm) × font-size` plus letter-spacing. DRIVING at 15 px = 87.8 px. Use it for the top-bar name rule (≤ 122 px) and the side-label fit. |

**Byte budget (Atlas rule, total embedded-font bytes no larger than today):** this file is under `oswald-brand.woff2` (2,896 B) **only if Oswald is removed in the same story**. Both together exceed the ceiling.

**Why it is under `specs/`:** the cutting bench's enforced surface is `specs/**`. US-887 copies `michroma-brand.woff2` and `OFL-michroma.txt` to `src/pi/ui/assets/fonts/` and embeds the woff2 as a `data:` URI in `tokens.css`, exactly as Oswald is embedded. The md5 above is the check that the copy is unchanged.
