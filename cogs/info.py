import discord
from discord import app_commands
from discord.ext import commands

import requests
import re
import io
import os
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
from assets.exp import level_exp

# ====== FILE PATHS ======
BOX_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "box.png")
ARCH_MASK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "box_arch_mask.png")
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "arial.ttf")

# ====== PLACEMENT CONFIG ======
# Keep a tiny inset so pixels never kiss the border (applied to arch bbox)
INSET_X = 2
TOP_MARGIN = 4
FOOTLINE_MARGIN = 6  # feet land this many px above arch’s bottom edge

# Resize policy
UPSCALE_SMALL = False          # True to let small sprites grow a bit
MAX_HEIGHT_RATIO = 1.00        # 1.00 = fit exactly to inner box; 0.98 leaves headroom
MIN_HEIGHT_RATIO = 0.90        # only used if UPSCALE_SMALL=True

# Body/feet detection params
BOTTOM_FRAC = 0.55     # analyze bottom 55% of sprite
BAND_THRESH = 0.40     # keep columns >=40% of peak alpha (ignores skinny weapons)
MIN_BAND_W  = 8        # minimum contiguous body band width
ALPHA_T     = 32       # pixel alpha considered "solid" for feet detection
FEET_WINDOW_HALF = 6   # search feet only around band center ± this px
FEET_PERCENTILE = 0.90 # 90th percentile of lowest pixels ≈ near actual feet
# ===============================


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._arch_mask_full = None   # L-mode, same size as base
        self._arch_bbox = None        # (x0, y0, x1, y1) tight bbox of the arch

    # --- load base and mask ---
    def _load_base_and_mask(self):
        # base template
        img = Image.open(BOX_PATH).convert("RGBA")

        # mask (must be same size as base)
        mask = Image.open(ARCH_MASK_PATH).convert("L")
        if mask.size != img.size:
            raise ValueError(f"Arch mask size {mask.size} must match base {img.size}")

        # arch bbox (tight)
        bbox = mask.getbbox()
        if not bbox:
            raise ValueError("Arch mask appears empty (no nonzero pixels).")
        return img, mask, bbox

    # --- core paste, guaranteed clipped to mask ---
    def _paste_character(self, base_img: Image.Image, arch_mask: Image.Image, arch_bbox, char_img: Image.Image):
        ax0, ay0, ax1, ay1 = arch_bbox
        aw, ah = ax1 - ax0, ay1 - ay0

        # safe inner-rectangle to fully contain sprite
        inner_x0 = ax0 + INSET_X
        inner_x1 = ax1 - INSET_X
        inner_y0 = ay0 + TOP_MARGIN
        inner_y1 = ay1 - FOOTLINE_MARGIN
        inner_w = max(1, inner_x1 - inner_x0)
        inner_h = max(1, inner_y1 - inner_y0)

        # normalize sprite
        char = ImageOps.exif_transpose(char_img.convert("RGBA"))

        # trim transparent padding
        a_full = char.split()[-1]
        bbox = a_full.getbbox() or char.getbbox()
        if bbox:
            char = char.crop(bbox)

        # --- resize to fit inner box (always fits) ---
        fit_scale = min(inner_w / char.width, inner_h / char.height)
        if char.width > inner_w or char.height > inner_h:
            scale = fit_scale * MAX_HEIGHT_RATIO
        else:
            if UPSCALE_SMALL:
                min_scale = max(
                    (inner_h * MIN_HEIGHT_RATIO) / char.height,
                    (inner_w * MIN_HEIGHT_RATIO) / char.width,
                )
                scale = max(1.0, min(min_scale, fit_scale * MAX_HEIGHT_RATIO))
            else:
                scale = 1.0

        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(round(char.width * scale)))
            new_h = max(1, int(round(char.height * scale)))
            char = char.resize((new_w, new_h), Image.LANCZOS)

        # --- body band & feet detection on resized sprite ---
        a = char.split()[-1]
        w, h = a.size
        y0 = int(h * (1 - BOTTOM_FRAC))
        px = a.load()

        # sum alpha by column on bottom slice
        col_sums = [0] * w
        for x in range(w):
            s = 0
            for y in range(y0, h):
                s += px[x, y]
            col_sums[x] = s

        peak = max(col_sums) if col_sums else 0
        if peak > 0:
            thresh = int(peak * BAND_THRESH)
            peak_x = max(range(w), key=lambda i: col_sums[i])
            left = peak_x
            right = peak_x
            while left - 1 >= 0 and col_sums[left - 1] >= thresh:
                left -= 1
            while right + 1 < w and col_sums[right + 1] >= thresh:
                right += 1
            if right - left + 1 < MIN_BAND_W:
                pad = (MIN_BAND_W - (right - left + 1)) // 2
                left = max(0, left - pad)
                right = min(w - 1, right + pad)
            centroid_x = (left + right) / 2
        else:
            left, right = 0, w - 1
            centroid_x = w / 2

        # feet search only around body center
        cx = int(round(centroid_x))
        half = max(FEET_WINDOW_HALF, (right - left + 1) // 3)
        fx0 = max(left, cx - half)
        fx1 = min(right, cx + half)

        feet_y = []
        for x in range(fx0, fx1 + 1):
            for y in range(h - 1, y0 - 1, -1):
                if px[x, y] >= ALPHA_T:
                    feet_y.append(y)
                    break

        if feet_y:
            feet_y.sort()
            idx = min(len(feet_y) - 1, int(len(feet_y) * FEET_PERCENTILE))
            foot_y_local = feet_y[idx]
        else:
            foot_y_local = h - 1

        # --- place: center by body band, anchor feet to footline, clamp inside arch bbox ---
        target_center_x = ax0 + aw / 2
        paste_x = int(round(target_center_x - centroid_x))
        footline_y = ay1 - FOOTLINE_MARGIN
        paste_y = footline_y - foot_y_local

        # clamp so the WHOLE sprite stays inside the arch *rectangle* (mask will handle the arch curve)
        paste_x = max(inner_x0, min(inner_x1 - w, paste_x))
        # top clamp:
        paste_y = max(inner_y0, paste_y)
        # feet (bottom) clamp: footline must be <= inner_y1
        max_paste_y = inner_y1 - foot_y_local
        paste_y = min(paste_y, max_paste_y)

        # build local mask: sprite alpha × arch mask under this sprite
        sprite_alpha = char.split()[-1]
        arch_crop = arch_mask.crop((paste_x, paste_y, paste_x + w, paste_y + h))
        final_mask = ImageChops.multiply(sprite_alpha, arch_crop)

        # paste (anything outside arch is 0-masked)
        base_img.paste(char, (paste_x, paste_y), final_mask)

    # ---------------- SLASH COMMAND ----------------
    @app_commands.command(name="info", description="Fetch character info")
    async def fetch_info(self, interaction: discord.Interaction, custom_input: str):
        await interaction.response.defer()

        # fetch page
        url = f"https://dreamms.gg/?stats={custom_input}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except Exception:
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(response.content, "html.parser")
        img_tag = soup.find("img", {"src": re.compile(r"https://api\\.dreamms\\.gg/api/gms/latest/character/.+")})
        img_url = img_tag["src"] if img_tag else None
        if not img_url:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return
        img_url = re.sub(r"/jump.*$", "", img_url)

        # load base + mask
        try:
            img, arch_mask, arch_bbox = self._load_base_and_mask()
        except Exception as e:
            await interaction.followup.send(f"Mask/base load error: {e}", ephemeral=True)
            return

        # fetch character sprite
        try:
            sprite_bytes = requests.get(img_url, timeout=15)
            sprite_bytes.raise_for_status()
            character_img = Image.open(io.BytesIO(sprite_bytes.content))
        except Exception:
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        # paste character (guaranteed clipped to arch)
        self._paste_character(img, arch_mask, arch_bbox, character_img)

        # draw text
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(FONT_PATH, 18)
        except Exception:
            await interaction.followup.send("Failed to load font.", ephemeral=True)
            return

        def safe_int(text, default=0):
            try:
                return int(str(text).replace(",", "").strip())
            except Exception:
                return default

        name = (soup.find("span", class_="name") or {}).get_text(strip=True) if soup.find("span", class_="name") else "Unknown"
        job = (soup.find("span", class_="job") or {}).get_text(strip=True) if soup.find("span", class_="job") else "Not found"
        level = safe_int((soup.find("span", class_="level") or {}).get_text(strip=True) if soup.find("span", class_="level") else "0")
        exp = safe_int((soup.find("span", class_="exp") or {}).get_text(strip=True) if soup.find("span", class_="exp") else "0")
        fame = (soup.find("span", class_="fame") or {}).get_text(strip=True) if soup.find("span", class_="fame") else "Not found"
        guild = (soup.find("span", class_="guild") or {}).get_text(strip=True) if soup.find("span", class_="guild") else "Not found"
        partner = (soup.find("span", class_="partner") or {}).get_text(strip=True) if soup.find("span", class_="partner") else "Not found"

        if level in level_exp and level_exp[level] > 0:
            pct = (exp / level_exp[level]) * 100
            level_info = f"{level} || ({pct:.2f}%)"
        else:
            level_info = str(level)

        x, y = 140, 10
        labels = ["Name:", "Job:", "Level:", "Fame:", "Guild:", "Partner:"]
        for label in labels:
            draw.text((x, y), label, font=font, fill=(255, 255, 255))
            y += 28

        x, y = 225, 10
        values = [f" {name}", f" {job}", f" {level_info}", f" {fame}", f" {guild}", f" {partner}"]
        for val in values:
            draw.text((x, y), val, font=font, fill=(0, 0, 0))
            y += 28

        # send
        with io.BytesIO() as buf:
            img.save(buf, "PNG")
            buf.seek(0)
            await interaction.followup.send(file=discord.File(fp=buf, filename="info_image.png"))


async def setup(bot):
    await bot.add_cog(Info(bot))
