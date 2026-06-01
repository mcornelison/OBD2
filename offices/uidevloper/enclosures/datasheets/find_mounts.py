import fitz

doc = fitz.open(r"Z:\o\OBD2v2\specs\vendor\OSOYOO-datasheet.pdf")
page = doc[0]

# PCB outline rect (found earlier): x[446.3,710.2]=85mm, y[226.8,401.7]=56mm
X0, X1 = 446.3, 710.2
Y0, Y1 = 226.8, 401.7
sx = 85.0 / (X1 - X0)
sy = 56.0 / (Y1 - Y0)
def mm(px, py):  # from PCB TOP-LEFT: (from_left, from_top)
    return round((px - X0) * sx, 1), round((py - Y0) * sy, 1)

# Mount holes = circle-like closed paths made of bezier curves, ~Phi3mm
# (radius ~1.5mm -> ~4.7pt; the ring pad a bit larger). Collect circle-ish paths.
cands = []
for d in page.get_drawings():
    r = d["rect"]
    w, h = r.width, r.height
    if w <= 0 or h <= 0:
        continue
    if abs(w - h) > max(2.5, 0.25*w):
        continue  # not round
    # count curve items (a circle is ~4 cubic beziers)
    ncurve = sum(1 for it in d["items"] if it[0] == "c")
    if ncurve < 2:
        continue
    if 5 <= w <= 16 and 5 <= h <= 16:
        cx, cy = (r.x0+r.x1)/2, (r.y0+r.y1)/2
        fl, ft = mm(cx, cy)
        # only within/near the PCB
        if -2 <= fl <= 87 and -2 <= ft <= 58:
            cands.append((fl, ft, round(w,1)))

# Mount holes sit ~3.5mm from top/bottom edges -> ft ~3.5 or ~52.5
print("Circle-like paths (from_left, from_top, dia_pt):")
for c in sorted(cands, key=lambda t:(t[1], t[0])):
    flag = "  <-- near top/bottom edge (HOLE?)" if (c[1] < 8 or c[1] > 48) else ""
    print(f"  ({c[0]:5.1f}, {c[1]:5.1f})  d={c[2]:4.1f}{flag}")
