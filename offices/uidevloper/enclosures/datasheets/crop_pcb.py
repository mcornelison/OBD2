import fitz

doc = fitz.open(r"Z:\o\OBD2v2\offices\uidevloper\enclosures\datasheets\2024009100_hdmi_datasheet.pdf")
page = doc[0]

# PCB diagram occupies roughly the right half of page 1. Crop generously.
clip = fitz.Rect(420, 195, 815, 420)
mat = fitz.Matrix(6, 6)  # 6x zoom
pix = page.get_pixmap(matrix=mat, clip=clip)
out = r"Z:\o\OBD2v2\offices\uidevloper\enclosures\datasheets\pcb_zoom.png"
pix.save(out)
print("saved", out, pix.width, "x", pix.height)
