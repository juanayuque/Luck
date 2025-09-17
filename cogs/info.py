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

# ====== CONFIG: match the galaxy window on box.png ======
# (left, top, right, bottom) bounds of the arched window
VIEWPORT = (28, 18, 160, 168)

# Keep a tiny inset so pixels never touch the arch border
INSET_X = 2            # left/right padding inside window
TOP_MARGIN = 4         # avoid hats touching the arch top
FOOTLINE_MARGIN = 6    # feet land this many px above window bottom

# Resize policy: ALWAYS fit inside the safe inner box (no upscaling unless you enable)
UPSCALE_SMALL = False
MAX_HEIGHT_RATIO = 1.00   # 1.00 = fit exactly to inner box; 0.98 leaves breathing room
MIN_HEIGHT_RATIO = 0.90   # used only if you set UPSCALE_SMALL=True

# Body/feet detection params
BOTTOM_FRAC = 0.55     # analyze bottom 55% of sprite
BAND_THRESH = 0.40     # keep columns >=40% of peak alpha (ignores skinny weapons)
MIN_BAND_W  = 8        # minimum contiguous band width
ALPHA_T     = 32       # pixel alpha considered "solid" for feet detection
FEET_WINDOW_HALF = 6   # search feet only around band center ± this px
FEET_PERCENTILE = 0.90 # 90th percentile of lowest pixels ≈ near actual feet
# ========================================================


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._arch_mask_cache = None  # cache arch mask per base-image size

    # ---- helpers for sprite normalization & clipping ----
    def _build_arch_mask(self, base_size, viewport):
        vx0, vy0, vx1, vy1 = viewport
        w, h = base_size
        mask = Image.new("L", (w, h), 0)
        mdraw = ImageDraw.Draw(mask)

        vw, vh = vx1 - vx0, vy1 - vy0
        r = vw // 2  # assume the arch cap is a perfect semicircle

        # rectangular shaft of the arch
        mdraw.rectangle([vx0, vy0 + r, vx1, vy1], fill=255)
        # semicircle cap on top (draw as pieslice of a full circle)
        mdraw.pieslice([vx0, vy0, vx1, vy0 + 2 * r], start=180, end=360, fill=255)
        return mask

    def _paste_character_clipped(self, base_img: Image.Image, char_img: Image.Image):
        # cache arch mask for this base size
        if self._arch_mask_cache is None or self._arch_mask_cache.size != base_img.size:
            self._arch_mask_cache = self._build_arch_mask(base_img.size, VIEWPORT)

        vx0, vy0, vx1, vy1 = VIEWPORT
        win_w, win_h = (vx1 - vx0), (vy1 - vy0)

        # Safe inner-rectangle the sprite must fully fit into
        inner_x0 = vx0 + INSET_X
        inner_x1 = vx1 - INSET_X
        inner_y0 = vy0 + TOP_MARGIN
        inner_y1 = vy1 - FOOTLINE_MARGIN
        inner_w = max(1, inner_x1 - inner_x0)
        inner_h = max(1, inner_y1 - inner_y0)

        # Normalize sprite (fix EXIF orientation, force RGBA)
        char = ImageOps.exif_transpose(char_img.convert("RGBA"))

        # Trim transparent padding using alpha
        alpha_full = char.split()[-1]
        bbox = alpha_full.getbbox() or char.getbbox()
        if bbox:
            char = char.crop(bbox)

        # ---- Resize: ALWAYS ensure sprite fits the inner box ----
        # Compute scale to fit width/height (no distortion)
        scale_fit = min(inner_w / char.width, inner_h / char.height)

        if char.width > inner_w or char.height > inner_h:
            # Shrink; optionally leave a tiny headroom
            scale = scale_fit * MAX_HEIGHT_RATIO
        else:
            if UPSCALE_SMALL:
                # Gentle upscale so small sprites aren't tiny
                min_scale = max(
                    (inner_h * MIN_HEIGHT_RATIO) / char.height,
                    (inner_w * MIN_HEIGHT_RATIO) / char.width,
                )
                scale = max(1.0, min(min_scale, scale_fit * MAX_HEIGHT_RATIO))
            else:
                scale = 1.0  # strict no-upscale

        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(round(char.width * scale)))
            new_h = max(1, int(round(char.height * scale)))
            char_fit = char.resize((new_w, new_h), Image.LANCZOS)
        else:
            char_fit = char
        # ------------------------------------------------------------------

        # ---- Analyze bottom slice to find body band and feet line ----
        a = char_fit.split()[-1]
        w, h = a.size
        y0 = int(h * (1 - BOTTOM_FRAC))
        px = a.load()

        # Column alpha sums over bottom slice
        col_sums = [0] * w
        for x in range(w):
            s = 0
            for y in range(y0, h):
                s += px[x, y]
            col_sums[x] = s

        # Peak-based contiguous band around torso/legs
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
            # ensure a minimum band width
            if right - left + 1 < MIN_BAND_W:
                pad = (MIN_BAND_W - (right - left + 1)) // 2
                left = max(0, left - pad)
                right = min(w - 1, right + pad)
            centroid_x = (left + right) / 2
        else:
            left, right = 0, w - 1
            centroid_x = w / 2  # fallback

        # Feet detection: only search a narrow window around the band center
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
            foot_y_local = feet_y[idx]  # near the lowest
        else:
            foot_y_local = h - 1  # fallback
        # ------------------------------------------------------------------

        # ---- Placement: center by body band, anchor feet to the footline ----
        target_center_x = vx0 + win_w / 2
        paste_x = int(round(target_center_x - centroid_x))
        footline_y = vy1 - FOOTLINE_MARGIN
        paste_y = footline_y - foot_y_local

        # Hard clamp so the WHOLE sprite rect stays inside the inner box
        paste_x = max(inner_x0, min(inner_x1 - w, paste_x))
        paste_y = max(inner_y0, min(inner_y1 - (h - (h - 1 - foot_y_local) - 1), paste_y))
        # Explanation of Y clamp:
        #   top >= inner_y0
        #   bottom (footline) <= inner_y1; since we anchor feet to footline_y, and feet
        #   are at y = foot_y_local within the sprite, the effective bottom is paste_y + foot_y_local.

        # ------------------------------------------------------------------

        # Local arch mask at the paste rectangle
        sprite_alpha = char_fit.split()[-1]
        local_arch = self._arch_mask_cache.crop(
            (paste_x, paste_y, paste_x + w, paste_y + h)
        )
        final_mask = ImageChops.multiply(sprite_alpha, local_arch)

        # Paste (any outside area is already masked to 0)
        base_img.paste(char_fit, (paste_x, paste_y), final_mask)

    @app_commands.command(name="info", description="Fetch character info")
    async def fetch_info(self, interaction: discord.Interaction, custom_input: str):
        await interaction.response.defer()  # avoid timeout

        url = f"https://dreamms.gg/?stats={custom_input}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except Exception:
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(response.content, "html.parser")
        img_tag = soup.find("img", {"src": re.compile(r"https://api\.dreamms\.gg/api/gms/latest/character/.+")})
        img_url = img_tag["src"] if img_tag else None

        if not img_url:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return

        img_url_cleaned = re.sub(r"/jump.*$", "", img_url)

        # Load base template
        try:
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "box.png")
            img = Image.open(img_path).convert("RGBA")
        except Exception:
            await interaction.followup.send("Failed to load base image.", ephemeral=True)
            return

        # Fetch character sprite
        try:
            response_img = requests.get(img_url_cleaned, timeout=15)
            response_img.raise_for_status()
            character_img = Image.open(io.BytesIO(response_img.content))
        except Exception:
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        # Paste the character confined to the galaxy arch
        self._paste_character_clipped(img, character_img)

        draw = ImageDraw.Draw(img)
        try:
            font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "arial.ttf")
            font = ImageFont.truetype(font_path, 18)
        except Exception:
            await interaction.followup.send("Failed to load font.", ephemeral=True)
            return

        # Safely parse fields
        def safe_int(text, default=0):
            try:
                return int(str(text).replace(",", "").strip())
            except Exception:
                return default

        name = soup.find("span", class_="name")
        job = soup.find("span", class_="job")
        level = soup.find("span", class_="level")
        exp = soup.find("span", class_="exp")
        fame = soup.find("span", class_="fame")
        guild = soup.find("span", class_="guild")
        partner = soup.find("span", class_="partner")

        name = name.text.strip() if name else "Unknown"
        job = job.text.strip() if job else "Not found"
        level_val = safe_int(level.text if level else "0", 0)
        exp_val = safe_int(exp.text if exp else "0", 0)
        fame = fame.text.strip() if fame else "Not found"
        guild = guild.text.strip() if guild else "Not found"
        partner = partner.text.strip() if partner else "Not found"

        # Level progress %
        if level_val in level_exp and level_exp[level_val] > 0:
            percentage = (exp_val / level_exp[level_val]) * 100
            level_info = f"{level_val} || ({percentage:.2f}%)"
        else:
            level_info = str(level_val)

        # Labels
        x, y = 140, 10
        labels = ["Name:", "Job:", "Level:", "Fame:", "Guild:", "Partner:"]
        for label in labels:
            draw.text((x, y), label, font=font, fill=(255, 255, 255))
            y += 28

        # Values
        x, y = 225, 10
        values = [f" {name}", f" {job}", f" {level_info}", f" {fame}", f" {guild}", f" {partner}"]
        for val in values:
            draw.text((x, y), val, font=font, fill=(0, 0, 0))
            y += 28

        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)
            await interaction.followup.send(file=discord.File(fp=image_binary, filename="info_image.png"))

async def setup(bot):
    await bot.add_cog(Info(bot))
