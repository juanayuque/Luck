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

# Feet anchor line: how far ABOVE the viewport bottom should the feet land?
FOOTLINE_MARGIN = 4  # pixels above vy1; increase if toes still touch the border

# Resize policy
UPSCALE_SMALL = False          # False = only shrink; True = allow gentle upscaling
MIN_HEIGHT_RATIO = 0.90        # if UPSCALE_SMALL=True, target at least this much height
MAX_HEIGHT_RATIO = 0.98        # when shrinking, keep tiny headroom (~98% max)

# Body/feet detection params
BOTTOM_FRAC = 0.55    # use bottom 55% of the sprite to analyze body/feet
BAND_THRESH = 0.40    # keep columns >=40% of the peak alpha in that slice
MIN_BAND_W  = 6       # ensure at least this band width
ALPHA_T     = 32      # alpha threshold to consider a pixel "solid" for feet
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
        v_w, v_h = (vx1 - vx0), (vy1 - vy0)

        # Normalize sprite (fix EXIF orientation, force RGBA)
        char = ImageOps.exif_transpose(char_img.convert("RGBA"))

        # Trim transparent padding using alpha
        alpha = char.split()[-1]
        bbox = alpha.getbbox() or char.getbbox()
        if bbox:
            char = char.crop(bbox)

        # --- Resize policy (only shrink unless gentle upscale enabled) ---
        vw, vh = v_w, v_h
        scale_fit_w = vw / char.width
        scale_fit_h = vh / char.height
        scale_fit = min(scale_fit_w, scale_fit_h)

        if char.width > vw or char.height > vh:
            # Need to shrink; keep a small headroom via MAX_HEIGHT_RATIO
            target_scale_h = (vh * MAX_HEIGHT_RATIO) / char.height
            target_scale_w = (vw * MAX_HEIGHT_RATIO) / char.width
            scale = min(scale_fit, target_scale_h, target_scale_w)
        else:
            if UPSCALE_SMALL:
                min_scale_h = (vh * MIN_HEIGHT_RATIO) / char.height
                min_scale_w = (vw * MIN_HEIGHT_RATIO) / char.width
                scale = max(1.0, min(min_scale_h, min_scale_w))
            else:
                scale = 1.0  # strict no-upscale

        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(round(char.width * scale)))
            new_h = max(1, int(round(char.height * scale)))
            char_fit = char.resize((new_w, new_h), Image.LANCZOS)
        else:
            char_fit = char
        # ------------------------------------------------------------------

        # ---- Analyze bottom slice to find body band and the feet line ----
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
            if right - left + 1 < MIN_BAND_W:
                pad = (MIN_BAND_W - (right - left + 1)) // 2
                left = max(0, left - pad)
                right = min(w - 1, right + pad)
            centroid_x = (left + right) / 2
        else:
            left, right = 0, w - 1
            centroid_x = w / 2  # fallback

        # Feet detection: scan bottom-up within the body band, gather lowest solid pixels
        foot_candidates = []
        for x in range(left, right + 1):
            for y in range(h - 1, y0 - 1, -1):
                if px[x, y] >= ALPHA_T:  # "solid" pixel
                    foot_candidates.append(y)
                    break  # this column's lowest pixel found

        if foot_candidates:
            foot_y_local = sorted(foot_candidates)[len(foot_candidates) // 2]  # median for robustness
        else:
            foot_y_local = h - 1  # fallback if totally empty (unlikely)
        # ------------------------------------------------------------------

        # ---- Placement: center by body band, anchor feet to fixed FOOTLINE ----
        target_center_x = vx0 + v_w / 2
        paste_x = int(round(target_center_x - centroid_x))

        footline_y = vy1 - FOOTLINE_MARGIN  # absolute y on the canvas
        paste_y = footline_y - foot_y_local  # align sprite's feet to the footline

        # No horizontal clamp (to avoid nudging wide poses); vertical overflow is fine,
        # arch mask will clip anything outside the window.
        # ------------------------------------------------------------------

        # Local arch mask at the paste rectangle (crop handles out-of-bounds by padding with 0)
        sprite_alpha = char_fit.split()[-1]
        local_arch = self._arch_mask_cache.crop(
            (paste_x, paste_y, paste_x + char_fit.width, paste_y + char_fit.height)
        )
        final_mask = ImageChops.multiply(sprite_alpha, local_arch)

        # Paste (Pillow supports negative paste coords; off-canvas is discarded)
        base_img.paste(char_fit, (paste_x, paste_y), final_mask)

    @app_commands.command(name="info", description="Fetch character info")
    async def fetch_info(self, interaction: discord.Interaction, custom_input: str):
        await interaction.response.defer()  # avoid timeout

        print(f"Fetching info for: {custom_input}")
        url = f"https://dreamms.gg/?stats={custom_input}"

        try:
            response = requests.get(url, timeout=15)
            print(f"HTTP response status: {response.status_code}")
            response.raise_for_status()
        except Exception as e:
            print(f"Error fetching page: {e}")
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(response.content, "html.parser")
        img_tag = soup.find("img", {"src": re.compile(r"https://api\.dreamms\.gg/api/gms/latest/character/.+")})
        img_url = img_tag["src"] if img_tag else None
        print(f"Image URL: {img_url}")

        if not img_url:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return

        # Clean '/jump...' suffix if present
        img_url_cleaned = re.sub(r"/jump.*$", "", img_url)

        # Load base template
        try:
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "box.png")
            img = Image.open(img_path).convert("RGBA")
            print("Base image loaded")
        except Exception as e:
            print(f"Error loading base image: {e}")
            await interaction.followup.send("Failed to load base image.", ephemeral=True)
            return

        # Fetch character sprite
        try:
            response_img = requests.get(img_url_cleaned, timeout=15)
            print(f"Image HTTP response status: {response_img.status_code}")
            response_img.raise_for_status()
            character_img = Image.open(io.BytesIO(response_img.content))
            print("Character image loaded")
        except Exception as e:
            print(f"Error loading character image: {e}")
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        # ==== Paste the character confined to the galaxy arch ====
        self._paste_character_clipped(img, character_img)
        print("Character image pasted (clipped to arch)")

        draw = ImageDraw.Draw(img)
        try:
            font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "arial.ttf")
            font = ImageFont.truetype(font_path, 18)
            print("Font loaded")
        except Exception as e:
            print(f"Error loading font: {e}")
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

        print("Got to calculate stuff")
        # Calculate level progress %
        if level_val in level_exp and level_exp[level_val] > 0:
            percentage = (exp_val / level_exp[level_val]) * 100
            level_info = f"{level_val} || ({percentage:.2f}%)"
        else:
            level_info = str(level_val)
        print("Image got calculated")

        # Draw labels and values
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

        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)
            print("Image saved to binary")
            await interaction.followup.send(file=discord.File(fp=image_binary, filename="info_image.png"))
        print("Info sent successfully")


async def setup(bot):
    await bot.add_cog(Info(bot))
    print("Info cog loaded")
