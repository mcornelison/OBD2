import fitz

doc = fitz.open(r"Z:\o\OBD2v2\offices\uidevloper\enclosures\datasheets\2024009100_hdmi_datasheet.pdf")
page = doc[0]

# PCB diagram reference frame (from dimension lines found earlier):
# PCB x in [446.3, 710.2] (=85mm), y in [239.3, 390.1] (=49mm), y increases DOWN.
X0, X1 = 446.3, 710.2
Y0, Y1 = 239.3, 390.1
sx = 85.0 / (X1 - X0)
sy = 49.0 / (Y1 - Y0)

def to_mm(px, py):
    # mm from PCB top-left; also give from-left and from-top, and from bottom/right
    mx = (px - X0) * sx
    my = (py - Y0) * sy
    return round(mx, 1), round(my, 1)

words = page.get_text("words")  # x0,y0,x1,y1,word,block,line,wordno
print("Dimension-like tokens on the PCB diagram (word @ from-left,from-top mm):")
for w in words:
    x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
    cx, cy = (x0+x1)/2, (y0+y1)/2
    if cx < X0 - 30 or cx > X1 + 35:
        continue
    if cy < Y0 - 35 or cy > Y1 + 35:
        continue
    t = txt.strip()
    # keep numeric-ish dimension tokens
    if any(ch.isdigit() for ch in t):
        mm = to_mm(cx, cy)
        print(f"  '{t:>10}'  pdf=({cx:6.1f},{cy:6.1f})  ~mm_from_TL=({mm[0]:6.1f},{mm[1]:6.1f})")
