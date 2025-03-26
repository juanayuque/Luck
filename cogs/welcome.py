import discord
import requests
import urllib.parse
import random
import time
from bs4 import BeautifulSoup
from discord.ext import commands
from PIL import Image, ImageSequence
import os

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.max_retries = 3
        self.initial_timeout = 15
        self.retry_delay = 5

    @discord.app_commands.command(
        name="welcome", 
        description="Welcomes up to 4 characters with their animated sprites"
    )
    async def welcome_character(
        self, 
        interaction: discord.Interaction, 
        character1: str,
        character2: str = None,
        character3: str = None,
        character4: str = None
    ):
        await interaction.response.defer()
        
        # Collect all provided characters (excluding None values)
        characters = [c for c in [character1, character2, character3, character4] if c is not None]
        print(f"[DEBUG] Processing characters: {', '.join(characters)}")

        # Process all characters with retries
        gif_paths = []
        for char in characters:
            for attempt in range(self.max_retries):
                try:
                    gif_path = await self.process_character(char)
                    if gif_path:
                        gif_paths.append(gif_path)
                        break
                    else:
                        print(f"[WARNING] Attempt {attempt + 1} failed for {char}")
                except Exception as e:
                    print(f"[ERROR] Attempt {attempt + 1} failed for {char}: {e}")
                
                if attempt < self.max_retries - 1:
                    print(f"[DEBUG] Retrying {char} in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
            else:
                self.cleanup_files(gif_paths)
                await interaction.followup.send(f"Failed to process character after {self.max_retries} attempts: {char}", ephemeral=True)
                return

        # Combine all GIFs horizontally if multiple
        if len(gif_paths) > 1:
            final_gif_path = await self.combine_gifs_horizontally(gif_paths)
            if not final_gif_path:
                self.cleanup_files(gif_paths)
                await interaction.followup.send("Failed to combine character GIFs.", ephemeral=True)
                return
        else:
            final_gif_path = gif_paths[0]

        # Generate welcome message with all character names
        welcome_msg = self.generate_welcome_message(characters)

        # Send the final GIF
        try:
            file = discord.File(final_gif_path, filename="welcome.gif")
            embed = discord.Embed(
                title=welcome_msg,
                color=discord.Color.random()  # This generates a random color
            )
            embed.set_image(url="attachment://welcome.gif")
            await interaction.followup.send(embed=embed, file=file)
            
            # Clean up all files
            self.cleanup_files(gif_paths)
            if len(gif_paths) > 1:  # Only remove combined GIF if we created one
                os.remove(final_gif_path)
                
        except Exception as e:
            print(f"[ERROR] Failed to send GIF: {e}")
            self.cleanup_files(gif_paths)
            if len(gif_paths) > 1 and os.path.exists(final_gif_path):
                os.remove(final_gif_path)
            await interaction.followup.send(f"Error sending GIF: {e}", ephemeral=True)

    def generate_welcome_message(self, characters):
        """Generate grammatically correct welcome message"""
        if len(characters) == 1:
            return f"Welcome {characters[0]}!"
        elif len(characters) == 2:
            return f"Welcome {characters[0]} and {characters[1]}!"
        else:
            names_except_last = ", ".join(characters[:-1])
            return f"Welcome {names_except_last}, and {characters[-1]}!"

    async def process_character(self, ign: str):
        """Process a single character with retries and timeouts"""
        print(f"[DEBUG] Processing character: {ign}")

        # Scrape the character image with retry logic
        base_url = f"https://dreamms.gg/?stats={ign}"
        print(f"[DEBUG] Fetching URL: {base_url}")

        try:
            response = requests.get(base_url, timeout=self.initial_timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch character data: {e}")
            raise

        soup = BeautifulSoup(response.content, 'html.parser')
        img_tag = soup.find('img', {'src': lambda x: x and 'api.dreamms.gg' in x})

        if not img_tag:
            print("[ERROR] Character image not found on page.")
            raise ValueError("Character image not found")

        decoded_url = urllib.parse.unquote(img_tag['src'])
        print(f"[DEBUG] Extracted image URL: {decoded_url}")

        # Extract skin ID and items part
        parts = decoded_url.split("/")
        if len(parts) < 10:
            print("[ERROR] Unexpected URL format.")
            raise ValueError("Unexpected URL format")

        skin_id = parts[7]
        items_part = parts[8].rstrip(",")

        # Modify only weapon (6) and cape (9) to be 0
        if items_part:  # Only process if we have items
            items_list = items_part.split(",")
            if len(items_list) > 6:  # Ensure weapon position exists
                items_list[6] = "0"  # Set weapon to 0
            if len(items_list) > 9:  # Ensure cape position exists
                items_list[9] = "0"  # Set cape to 0
            items_part = ",".join(items_list)

        print(f"[DEBUG] Skin ID: {skin_id}")
        print(f"[DEBUG] Modified Items: {items_part}")

        # Randomly choose an animation type
        animation_type = random.choice(["stand1", "stand2", "walk1", "walk2", "fly"])
        print(f"[DEBUG] Selected animation: {animation_type}")

        # Reconstruct the character animation API URL
        encoded_items = urllib.parse.quote(items_part, safe=",")
        new_character_url = (
            f"https://api.dreamms.gg/api/gms/latest/character/animated/{skin_id}/{encoded_items}/{animation_type}/"
            f"&renderMode=Centered&resize=1.gif"
        )

        print(f"[DEBUG] New Character API URL: {new_character_url}")

    # Rest of the download and processing logic remains the same...
    # [Keep the existing download and GIF validation code here]

        # Download the GIF with retry logic
        for attempt in range(self.max_retries):
            try:
                gif_response = requests.get(new_character_url, stream=True, timeout=self.initial_timeout)
                if gif_response.status_code != 200:
                    print(f"[ERROR] Failed to download character GIF. Status Code: {gif_response.status_code}")
                    continue

                gif_path = f"temp_{ign}.gif"
                with open(gif_path, "wb") as f:
                    for chunk in gif_response.iter_content(1024):
                        f.write(chunk)

                # Verify the GIF is valid
                try:
                    with Image.open(gif_path) as test_gif:
                        test_gif.seek(0)
                        test_gif.seek(1)  # Test seeking to second frame
                    return gif_path
                except Exception as e:
                    print(f"[ERROR] Invalid GIF file for {ign}: {e}")
                    os.remove(gif_path)
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                    continue

            except requests.RequestException as e:
                print(f"[ERROR] Download attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                continue

        raise Exception(f"Failed to download valid GIF after {self.max_retries} attempts")

    async def combine_gifs_horizontally(self, gif_paths):
        """Combine multiple GIFs horizontally while aligning them to the ground."""
        try:
            gifs = [Image.open(path) for path in gif_paths]
            min_frames = min(gif.n_frames for gif in gifs)
            max_height = max(gif.size[1] for gif in gifs)  # Find tallest GIF
            
            frames = []
            for frame_idx in range(min_frames):
                combined_width = sum(gif.size[0] for gif in gifs)  # Total width of combined image
                new_frame = Image.new("RGBA", (combined_width, max_height))  # Base frame
                
                x_offset = 0
                for gif in gifs:
                    gif.seek(frame_idx)
                    frame = gif.convert("RGBA")
                    
                    y_offset = max_height - frame.size[1]  # Align to bottom
                    new_frame.paste(frame, (x_offset, y_offset), frame)
                    x_offset += frame.size[0]
                
                frames.append(new_frame)

            for gif in gifs:
                gif.close()

            if not frames:
                print("[ERROR] No valid frames were combined")
                return None

            final_gif_path = "combined_welcome.gif"
            frames[0].save(
                final_gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=gifs[0].info.get('duration', 100),
                loop=0,
                disposal=2,
                optimize=True
            )

            return final_gif_path

        except Exception as e:
            print(f"[ERROR] Failed to combine GIFs: {e}")
            return None

    def cleanup_files(self, file_paths):
        """Clean up temporary files"""
        for path in file_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    print(f"[DEBUG] Removed temporary file: {path}")
            except Exception as e:
                print(f"[WARNING] Failed to remove {path}: {e}")

async def setup(bot):
    await bot.add_cog(Welcome(bot))