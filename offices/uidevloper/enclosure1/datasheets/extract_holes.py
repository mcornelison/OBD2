import fitz

doc = fitz.open(r"Z:\o\OBD2v2\offices\uidevloper\enclosures\datasheets\2024009100_hdmi_datasheet.pdf")
page = doc[0]
print("PAGE SIZE pts:", page.rect)

draws = page.get_drawings()
print("num drawings:", len(draws))

# Candidate circles: small, near-square bounding boxes on the RIGHT half (PCB diagram).
# Page width ~ from rect; PCB diagram is on the right side.
pw = page.rect.width
circles = []
rects = []
for d in draws:
    r = d["rect"]
    w, h = r.width, r.height
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    # near-square and small => candidate hole (Phi 3mm). Scale unknown yet.
    if 3 < w < 18 and 3 < h < 18 and abs(w - h) < 4:
        circles.append((round(cx, 1), round(cy, 1), round(w, 1), round(h, 1)))
    # large rectangles (PCB outline / glass outline)
    if w > 150 or h > 120:
        rects.append((round(r.x0,1), round(r.y0,1), round(r.x1,1), round(r.y1,1), round(w,1), round(h,1)))

print("\n-- LARGE RECTS (x0,y0,x1,y1,w,h) --")
for rr in sorted(rects, key=lambda t: -t[4]*t[5]):
    print(rr)

print("\n-- CANDIDATE CIRCLES (cx,cy,w,h) on RIGHT half --")
for c in sorted(circles):
    if c[0] > pw * 0.45:
        print(c)
