import discord
import requests
import re
import io
import os
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands
from assets.exp import level_exp

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="info", description="Fetch character info")
    async def fetch_info(self, interaction: discord.Interaction, custom_input: str):
        await interaction.response.defer()  # Defer the response to avoid timeout

        print(f"Fetching info for: {custom_input}")
        url = f'https://dreamms.gg/?stats={custom_input}'
        response = requests.get(url)
        print(f"HTTP response status: {response.status_code}")

        if response.status_code != 200:
            await interaction.followup.send("Failed to retrieve character data.", ephemeral=True)
            return

        soup = BeautifulSoup(response.content, 'html.parser')
        img_tag = soup.find('img', {'src': re.compile(r"https://api\.dreamms\.gg/api/gms/latest/character/.+")})
        img_url = img_tag['src'] if img_tag else None
        print(f"Image URL: {img_url}")

        # Attempt to remove '/jump' from img_url if available
        img_url_cleaned = re.sub(r'/jump.*$', '', img_url) if img_url else None

        if not img_url:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return

        try:
            
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "img", "box.png")
            img = Image.open(img_path)
            print("Base image loaded")
        except Exception as e:
            print(f"Error loading base image: {e}")
            await interaction.followup.send("Failed to load base image.", ephemeral=True)
            return

        # Attempt to remove '/jump' from img_url if available
        img_url_cleaned = re.sub(r'/jump.*$', '', img_url) if img_url else None

        

        # Try fetching the cleaned URL first
        response_img = requests.get(img_url_cleaned) if img_url_cleaned else None
        print(f"Image HTTP response status: {response_img.status_code}")
        if response_img.status_code != 200:
            await interaction.followup.send("Failed to retrieve character image.", ephemeral=True)
            return

        try:
            character_img = Image.open(io.BytesIO(response_img.content))
            print("Character image loaded")
        except Exception as e:
            print(f"Error loading character image: {e}")
            await interaction.followup.send("Failed to load character image.", ephemeral=True)
            return

        # Resize character image
        if character_img.height > 140:
            scale_factor = 100 / character_img.height
            new_width = int(character_img.width * scale_factor)
            character_img = character_img.resize((new_width, 90), Image.LANCZOS)
        print("Character image resized")

        img.paste(character_img, (35, 60), character_img)
        print("Character image pasted onto base image")

        draw = ImageDraw.Draw(img)
        try:
            font_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "arial.ttf") # Ensure the font file path is correct
            font = ImageFont.truetype(font_path, 18)  
            print("Font loaded")
        except Exception as e:
            print(f"Error loading font: {e}")
            await interaction.followup.send("Failed to load font.", ephemeral=True)
            return

        name = soup.find('span', class_='name').text.strip() if soup.find('span', class_='name') else "Unknown"
        job = soup.find('span', class_='job').text.strip() if soup.find('span', class_='job') else 'Not found'
        level = int(soup.find('span', class_='level').text.strip()) if soup.find('span', class_='level') else 'Not found'
        exp = int(soup.find('span', class_='exp').text.strip().replace(',', '')) if soup.find('span', class_='exp') else 0
        fame = soup.find('span', class_='fame').text.strip() if soup.find('span', class_='fame') else 'Not found'
        guild = soup.find('span', class_='guild').text.strip() if soup.find('span', class_='guild') else 'Not found'
        partner = soup.find('span', class_='partner').text.strip() if soup.find('span', class_='partner') else 'Not found'

        print("Got to calculate stuff")
        # Calculate the percentage of current level's required experience
        if level in level_exp and level_exp[level] > 0:
            percentage = (exp / level_exp[level]) * 100
            level_info = f"{level} || ({percentage:.2f}%)"
        else:
            level_info = str(level)

        print("Image got calculated")
        
        # Coordinates for drawing text on the image
        x, y = 140, 10
        messages = [
            {"text": f"Name:", "color": (255, 255, 255)},  # White
            {"text": f"Job:", "color": (255, 255, 255)},  # White
            {"text": f"Level:", "color": (255, 255, 255)},  # White
            {"text": f"Fame:", "color": (255, 255, 255)},  # White
            {"text": f"Guild:", "color": (255, 255, 255)},  # White
            {"text": f"Partner:", "color": (255, 255, 255)},  # White
        ]
        
        messagesvar = [
            {"text": f" {name}", "color": (0, 0, 0)},  # Black
            {"text": f" {job}", "color": (0, 0, 0)},  # Black
            {"text": f" {level_info}", "color": (0, 0, 0)},  # Black
            {"text": f" {fame}", "color": (0, 0, 0)},  # Black
            {"text": f" {guild}", "color": (0, 0, 0)},  # Black
            {"text": f" {partner}", "color": (0, 0, 0)},  # Black
        ]

        # Draw the labels and values on the image
        for message in messages:
            text, color = message["text"], message["color"]
            draw.text((x, y), text, font=font, fill=color)
            y += 28

        x, y = 225, 10
        for message in messagesvar:
            text, color = message["text"], message["color"]
            draw.text((x, y), text, font=font, fill=color)
            y += 28

        with io.BytesIO() as image_binary:
            img.save(image_binary, 'PNG')
            image_binary.seek(0)

            print("Image saved to binary")

            await interaction.followup.send(file=discord.File(fp=image_binary, filename='info_image.png'))
        print("Info sent successfully")

async def setup(bot):
    await bot.add_cog(Info(bot))
    print("Info cog loaded")