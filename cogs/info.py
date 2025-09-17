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
INSET_X = 2          # horizontal padding inside the arch bbox
TOP_MARGIN = 4       # min space from top
FOOTLINE_MARGIN = 6  # feet land this many px above arch bottom

# Base scaling policy
UPSCALE_SMALL = False      # only shrink by default (set True if you want mild upscaling)
MAX_HEIGHT_RATIO = 1.00    # when shrinking to the inner box, 1.00 = fit exactly
MIN_HEIGHT_RATIO = 0.90    # used only if UPSCALE_SMALL=True

# Body/feet detection
BOTTOM_FRAC = 0.55         # analyze bottom portion of the sprite
BAND_THRESH = 0.40         # columns >= 40% of peak alpha kept (ignores skinny weapons)
MIN_BAND_W  = 8
ALPHA_T     = 32           # alpha threshold for “solid” pixel
FEET_WINDOW_HALF = 6       # +/- window around body center to search for feet
FEET_PERCENTILE = 0.90     # near-the-lowest foot (robust to odd pixels)

# Fit-check loop (shrink until the whole sprite fits the mask)
FIT_SHRINK_FACTOR = 0.95   # 5% smaller on each iteration
FIT_MAX_ITERS     = 12     # up to ~46% shrink if really needed
# ===============================


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- utilities ----------
    def _load_base_and_mask(self):
        base = Image.open(BOX_PATH).convert("RGBA")
        mask = Image.open(ARCH_MASK_PATH).convert("L")
        if mask.size != base.size:
            raise ValueError(f"Arch mask size {mask.size} must match base {base.size}")
        bbox = mask.getbbox()
        if not bbox:
            raise ValueError("Arch mask appears empty.")
        return base, mask, bbox

    def _resize_to_inner_box(self, sprite, inner_w, inner_h):
        """Shrink to fit inner box; optionally allow gentle upscaling."""
        scale_fit = min(inner_w / sprite.width, inner_h / sprite.height)
        if sprite.width > inner_w or sprite.height > inner_h:
            scale = scale_fit * MAX_HEIGHT_RATIO
        else:
            if UPSCALE_SMALL:
                min_scale = max(
                    (inner_h * MIN_HEIGHT_RATIO) / sprite.height,
                    (inner_w * MIN_HEIGHT_RATIO) / sprite.width,
                )
                scale = max(1.0, min(min_scale, scale_fit * MAX_HEIGHT_RATIO))
            else:
                scale = 1.0

        if abs(scale - 1.0) < 1e-6:
            return sprite, 1.0
        new_size = (max(1, int(round(sprite.width * scale))),
                    max(1, int(round(sprite.height * scale))))
        return sprite.resize(new_size, Image.LANCZOS), scale

    def _body_band_and_centroid(self, alpha, y0):
        """Return (left, right, centroid_x) for the body band in bottom slice."""
        w, h = alpha.size
        px = alpha.load()
        col_sums = [0] * w
        for x in range(w):
            s = 0
            for y in range(y0, h):
                s += px[x, y]
            col_sums[x] = s

        peak = max(col_sums) if col_sums else 0
        if peak <= 0:
            return 0, w - 1, w / 2

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
        return left, right, centroid_x

    def _find_feet(self, alpha, y0, left, right, centroid_x):
        """Return foot_y_local using a narrow window around body center."""
        w, h = alpha.size
        px = alpha.load()
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

        if not feet_y:
            return h - 1
        feet_y.sort()
        idx = min(len(feet_y) - 1, int(len(feet_y) * FEET_PERCENTILE))
        return feet_y[idx]

    def _any_overflow(self, sprite_alpha, arch_mask_crop):
        """Return True if any sprite-opaque pixels would be outside the mask."""
        if sprite_alpha.size != arch_mask_crop.size:
            arch_mask_crop = arch_mask_crop.resize(sprite_alpha.size, Image.NEAREST)
        # binarize sprite alpha
        bin_alpha = sprite_alpha.point(lambda p: 255 if p >= ALPHA_T else 0, mode="L")
        # mask -> 0/255
        bin_mask = arch_mask_crop.point(lambda p: 255 if p > 0 else 0, mode="L")
        inv_mask = ImageChops.invert(bin_mask)
        outside = ImageChops.multiply(bin_alpha, inv_mask)
        return outside.getbbox() is not None

    # ---------- main paste logic ----------
    def _place_and_fit(self, base_img, arch_mask, arch_bbox, sprite_rgba):
        ax0, ay0, ax1, ay1 = arch_bbox
        aw, ah = ax1 - ax0, ay1 - ay0

        # inner box we guarantee to fit into
        inner_x0 = ax0 + INSET_X
        inner_x1 = ax1 - INSET_X
        inner_y0 = ay0 + TOP_MARGIN
        inner_y1 = ay1 - FOOTLINE_MARGIN
        inner_w = max(1, inner_x1 - inner_x0)
        inner_h = max(1, inner_y1 - inner_y0)

        # normalize & trim
        sprite = ImageOps.exif_transpose(sprite_rgba.convert("RGBA"))
        a_full = sprite.split()[-1]
        bbox = a_full.getbbox() or sprite.getbbox()
        if bbox:
            sprite = sprite.crop(bbox)

        # initial resize to inner box (so it's never huge)
        sprite, _ = self._resize_to_inner_box(sprite, inner_w, inner_h)

        # iterate: compute placement, check overflow vs mask; shrink if needed
        for _ in range(FIT_MAX_ITERS):
            a = sprite.split()[-1]
            w, h = a.size
            y0 = int(h * (1 - BOTTOM_FRAC))

            # body band + centroid
            left, right, centroid_x = self._body_band_and_centroid(a, y0)
            # feet
            foot_y_local = self._find_feet(a, y0, left, right, centroid_x)

            # center by body, anchor feet to footline
            target_center_x = ax0 + aw / 2
            paste_x = int(round(target_center_x - centroid_x))
            footline_y = ay1 - FOOTLINE_MARGIN
            paste_y = footline_y - foot_y_local

            # hard clamp to inner rectangle (keeps whole sprite inside bbox)
            paste_x = max(inner_x0, min(inner_x1 - w, paste_x))
            paste_y = max(inner_y0, min(inner_y1 - foot_y_local, paste_y))

            # check mask overflow (curved top edges etc.)
            arch_crop = arch_mask.crop((paste_x, paste_y, paste_x + w, paste_y + h))
            if not self._any_overflow(a, arch_crop):
                # safe to paste
                final_mask = ImageChops.multiply(a, arch_crop)
                base_img.paste(sprite, (paste_x, paste_y), final_mask)
                return

            # overflow: shrink and retry
            new_size = (max(1, int(round(w * FIT_SHRINK_FACTOR))),
                        max(1, int(round(h * FIT_SHRINK_FACTOR))))
            sprite = sprite.resize(new_size, Image.LANCZOS)

        # If we still overflow after all iterations (unlikely), paste as-is with mask.
        a = sprite.split()[-1]
        w, h = a.size
        y0 = int(h * (1 - BOTTOM_FRAC))
        left, right, centroid_x = self._body_band_and_centroid(a, y0)
        foot_y_local = self._find_feet(a, y0, left, right, centroid_x)
        target_center_x = ax0 + aw / 2
        paste_x = int(round(target_center_x - centroid_x))
        footline_y = ay1 - FOOTLINE_MARGIN
        paste_y = footline_y - foot_y_local
        paste_x = max(inner_x0, min(inner_x1 - w, paste_x))
        paste_y = max(inner_y0, min(inner_y1 - foot_y_local, paste_y))
        arch_crop = arch_mask.crop((paste_x, paste_y, paste_x + w, paste_y + h))
        final_mask = ImageChops.multiply(a, arch_crop)
        base_img.paste(sprite, (paste_x, paste_y), final_mask)

    # ---------- slash command ----------
    @app_commands.command(name="info", description="Fetch character info")
    async def fetch_info(self, interaction: discord.Interaction, custom_input: str):
        await interaction.response.defer()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }

        # fetch stats page
        url = f"https://dreamms.gg/?stats={custom_input}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
        except Exception:
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(r.content, "html.parser")

        # robust image finder
        img_url = None
        tag = soup.find("img", src=re.compile(r"https://api\.dreamms\.gg/api/.*/character/.+", re.I))
        if tag and tag.get("src"):
            img_url = tag["src"]
        if not img_url:
            tag = soup.select_one('img[src*="/character/"]')
            if tag and tag.get("src"):
                img_url = tag["src"]
        if not img_url:
            meta = soup.find("meta", attrs={"property": "og:image"})
            if meta and "content" in meta.attrs and "/character/" in meta["content"]:
                img_url = meta["content"]
        if not img_url:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return

        img_url = re.sub(r"/jump.*$", "", img_url)
        img_url = re.sub(r"\?.*$", "", img_url)

        # load base + arch mask
        try:
            img, arch_mask, arch_bbox = self._load_base_and_mask()
        except Exception as e:
            await interaction.followup.send(f"Mask/base load error: {e}", ephemeral=True)
            return

        # fetch sprite
        try:
            s = requests.get(img_url, headers=headers, timeout=15)
            s.raise_for_status()
            character_img = Image.open(io.BytesIO(s.content))
        except Exception:
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        # place with auto-shrink-until-fit
        self._place_and_fit(img, arch_mask, arch_bbox, character_img)

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

        def get_txt(cls, default="Not found"):
            el = soup.find("span", class_=cls)
            return el.text.strip() if el else default

        name = get_txt("name", "Unknown")
        job = get_txt("job")
        level = safe_int(get_txt("level", "0"))
        exp = safe_int(get_txt("exp", "0"))
        fame = get_txt("fame")
        guild = get_txt("guild")
        partner = get_txt("partner")

        if level in level_exp and level_exp[level] > 0:
            pct = (exp / level_exp[level]) * 100
            level_info = f"{level} || ({pct:.2f}%)"
        else:
            level_info = str(level)

        # Labels
        x, y = 140, 10
        for label in ["Name:", "Job:", "Level:", "Fame:", "Guild:", "Partner:"]:
            draw.text((x, y), label, font=font, fill=(255, 255, 255))
            y += 28

        # Values
        x, y = 225, 10
        for val in [f" {name}", f" {job}", f" {level_info}", f" {fame}", f" {guild}", f" {partner}"]:
            draw.text((x, y), val, font=font, fill=(0, 0, 0))
            y += 28

        with io.BytesIO() as buf:
            img.save(buf, "PNG")
            buf.seek(0)
            await interaction.followup.send(file=discord.File(fp=buf, filename="info_image.png"))


async def setup(bot):
    await bot.add_cog(Info(bot))
