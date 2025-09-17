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
INSET_X = 2
TOP_MARGIN = 4
FOOTLINE_MARGIN = 6  # feet land this many px above arch’s bottom edge

UPSCALE_SMALL = False
MAX_HEIGHT_RATIO = 1.00
MIN_HEIGHT_RATIO = 0.90

BOTTOM_FRAC = 0.55
BAND_THRESH = 0.40
MIN_BAND_W = 8
ALPHA_T = 32
FEET_WINDOW_HALF = 6
FEET_PERCENTILE = 0.90
# ===============================


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._arch_mask_full = None
        self._arch_bbox = None

    def _load_base_and_mask(self):
        img = Image.open(BOX_PATH).convert("RGBA")
        mask = Image.open(ARCH_MASK_PATH).convert("L")
        if mask.size != img.size:
            raise ValueError(f"Arch mask size {mask.size} must match base {img.size}")
        bbox = mask.getbbox()
        if not bbox:
            raise ValueError("Arch mask appears empty.")
        return img, mask, bbox

    def _paste_character(self, base_img: Image.Image, arch_mask: Image.Image, arch_bbox, char_img: Image.Image):
        ax0, ay0, ax1, ay1 = arch_bbox
        aw, ah = ax1 - ax0, ay1 - ay0

        inner_x0 = ax0 + INSET_X
        inner_x1 = ax1 - INSET_X
        inner_y0 = ay0 + TOP_MARGIN
        inner_y1 = ay1 - FOOTLINE_MARGIN
        inner_w = max(1, inner_x1 - inner_x0)
        inner_h = max(1, inner_y1 - inner_y0)

        char = ImageOps.exif_transpose(char_img.convert("RGBA"))

        a_full = char.split()[-1]
        bbox = a_full.getbbox() or char.getbbox()
        if bbox:
            char = char.crop(bbox)

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

        a = char.split()[-1]
        w, h = a.size
        y0 = int(h * (1 - BOTTOM_FRAC))
        px = a.load()

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

        target_center_x = ax0 + aw / 2
        paste_x = int(round(target_center_x - centroid_x))
        footline_y = ay1 - FOOTLINE_MARGIN
        paste_y = footline_y - foot_y_local

        paste_x = max(inner_x0, min(inner_x1 - w, paste_x))
        paste_y = max(inner_y0, min(inner_y1 - foot_y_local, paste_y))

        sprite_alpha = char.split()[-1]
        arch_crop = arch_mask.crop((paste_x, paste_y, paste_x + w, paste_y + h))
        final_mask = ImageChops.multiply(sprite_alpha, arch_crop)

        base_img.paste(char, (paste_x, paste_y), final_mask)

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

        url = f"https://dreamms.gg/?stats={custom_input}"
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print("Error fetching page:", e)
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(response.content, "html.parser")

        # --- robust image finder ---
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

        try:
            img, arch_mask, arch_bbox = self._load_base_and_mask()
        except Exception as e:
            await interaction.followup.send(f"Mask/base load error: {e}", ephemeral=True)
            return

        try:
            sprite_bytes = requests.get(img_url, headers=headers, timeout=15)
            sprite_bytes.raise_for_status()
            character_img = Image.open(io.BytesIO(sprite_bytes.content))
        except Exception as e:
            print("Error loading character image:", e)
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        self._paste_character(img, arch_mask, arch_bbox, character_img)

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

        with io.BytesIO() as buf:
            img.save(buf, "PNG")
            buf.seek(0)
            await interaction.followup.send(file=discord.File(fp=buf, filename="info_image.png"))


async def setup(bot):
    await bot.add_cog(Info(bot))
