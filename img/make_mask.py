from PIL import Image, ImageDraw

# Paths
src = "box.png"
out = "box_arch_mask.png"

# Load the full template
base = Image.open(src).convert("L")
w, h = base.size

# === Draw a clean arch shape on a blank mask ===
mask = Image.new("L", (w, h), 0)
draw = ImageDraw.Draw(mask)

# Adjust these to match your arch position/size exactly
arch_left = 28
arch_top = 18
arch_right = 140
arch_bottom = 168

arch_w = arch_right - arch_left
arch_h = arch_bottom - arch_top
radius = arch_w // 2  # arch cap radius (semicircle)

# bottom rectangular shaft
draw.rectangle([arch_left, arch_top + radius, arch_right, arch_bottom], fill=255)
# top semicircle
draw.pieslice([arch_left, arch_top, arch_right, arch_top + 2 * radius], start=180, end=360, fill=255)

mask.save(out)
print(f"Saved clean arch mask -> {out}")
