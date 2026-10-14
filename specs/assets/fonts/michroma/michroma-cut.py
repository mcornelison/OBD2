import sys, os, string, json, hashlib
from fontTools import subset, version as ftv
from fontTools.ttLib import TTFont
src, out = sys.argv[1], sys.argv[2]
TEXT = string.ascii_uppercase + string.digits + " -"
def cut(p):
    o = subset.Options(); o.flavor="woff2"; o.layout_features=[]; o.hinting=False
    o.desubroutinize=True; o.name_IDs=[0,1,2,3,4,5,6]; o.notdef_outline=False; o.drop_tables += ["DSIG"]
    f = TTFont(src); s = subset.Subsetter(o); s.populate(text=TEXT); s.subset(f); f.flavor="woff2"; f.save(p)
a, b = os.path.join(out,"a.woff2"), os.path.join(out,"michroma-brand.woff2")
cut(a); cut(b)
md5 = lambda p: hashlib.md5(open(p,"rb").read()).hexdigest()
print("size", os.path.getsize(b), "deterministic", md5(a)==md5(b), "md5", md5(b))
print("src sha256", hashlib.sha256(open(src,"rb").read()).hexdigest(), "fonttools", ftv)
f = TTFont(src); n = f["name"]
print("version", n.getDebugName(5), "| family", n.getDebugName(1))
cmap = f.getBestCmap(); hm = f["hmtx"]; upm = f["head"].unitsPerEm
adv = {c: round(hm[cmap[ord(c)]][0]/upm, 6) for c in TEXT}
# verify subset keeps identical advances
g = TTFont(b); gc = g.getBestCmap(); gh = g["hmtx"]
assert all(gh[gc[ord(c)]][0] == hm[cmap[ord(c)]][0] for c in TEXT) and g["head"].unitsPerEm == upm
json.dump({"font":"Michroma Regular 400","source":"https://raw.githubusercontent.com/google/fonts/main/ofl/michroma/Michroma-Regular.ttf",
  "unitsPerEm": upm, "note":"advance width per character in em (hmtx / unitsPerEm); no kerning (layout features stripped). width_px = sum(adv) * font_size_px + letter_spacing_em * font_size_px * (len-1)",
  "advanceEm": adv}, open(os.path.join(out,"michroma-advances.json"),"w"), indent=1, sort_keys=True)
print("DRIVING@15", round(sum(adv[c] for c in "DRIVING")*15,1))
