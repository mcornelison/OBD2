"""Write a 3MF model file from an STL.

WHY: the Bambu Studio CLI will not slice on this PC (exit -3 with the profile chain,
0xC0000005 without), so `slicer/slice-v5.ps1` cannot produce the usual sliced project
3mf. The CIO asked for 3mf files. This produces the other kind.

⚠️ WHAT THIS IS AND IS NOT.
  IS:     a 3MF *model* -- geometry, correct millimetre units, opens in Bambu Studio
          as an object sitting on the plate.
  IS NOT: a sliced project. No profile, no supports, no layer count, no print time.
          v4's slicer/*.3mf ARE sliced projects; these are not the same thing and must
          not be mistaken for them.

Usage:  python tests/stl_to_3mf.py <in.stl> <out.3mf> "<object name>"
"""
import os
import sys
import zipfile


def read_stl(path):
    """ASCII or binary STL -> (verts, tris) with vertices deduplicated."""
    import struct
    raw = []
    with open(path, "rb") as f:
        if f.read(5) == b"solid":
            f.seek(0)
            cur = []
            for line in f:
                s = line.strip()
                if s.startswith(b"vertex"):
                    cur.append(tuple(float(x) for x in s.split()[1:4]))
                    if len(cur) == 3:
                        raw.append(tuple(cur))
                        cur = []
        else:
            f.seek(80)
            n = struct.unpack("<I", f.read(4))[0]
            for _ in range(n):
                d = struct.unpack("<12fH", f.read(50))
                raw.append((d[3:6], d[6:9], d[9:12]))

    index, verts, tris = {}, [], []
    for tri in raw:
        ids = []
        for v in tri:
            # round to 1 nm; OpenSCAD emits far fewer real vertices than triangle corners
            key = (round(v[0], 6), round(v[1], 6), round(v[2], 6))
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            ids.append(index[key])
        if len(set(ids)) == 3:          # drop degenerates; 3MF validators reject them
            tris.append(ids)
    return verts, tris


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)

RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def build_model(verts, tris, name):
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
        "<metadata name=\"Application\">Iris / OpenSCAD (Eclipse OBD-II)</metadata>",
        '<resources><object id="1" type="model" name="%s"><mesh><vertices>' % name,
    ]
    out += ['<vertex x="%g" y="%g" z="%g"/>' % v for v in verts]
    out.append("</vertices><triangles>")
    out += ['<triangle v1="%d" v2="%d" v3="%d"/>' % tuple(t) for t in tris]
    out.append("</triangles></mesh></object></resources>")
    # identity transform; the part already sits with its print face on z=0
    out.append('<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build>')
    out.append("</model>")
    return "".join(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(dst)

    verts, tris = read_stl(src)
    model = build_model(verts, tris, name)

    tmp = dst + ".tmp"                       # never write the target in place
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)

    # gate on the copy before promoting it
    with zipfile.ZipFile(tmp) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit("corrupt member in %s: %s" % (tmp, bad))
        got = z.read("3D/3dmodel.model").decode("utf-8")
    if got.count("<triangle ") != len(tris) or got.count("<vertex ") != len(verts):
        raise SystemExit("round-trip mismatch, refusing to promote")
    os.replace(tmp, dst)

    print("%-22s %6d verts  %6d tris  %8d bytes"
          % (os.path.basename(dst), len(verts), len(tris), os.path.getsize(dst)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
