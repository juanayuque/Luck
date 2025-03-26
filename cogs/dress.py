import discord
import requests
import urllib.parse
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands


OUTFIT_PRESETS = {
    "moo": "0,0,1053263,0,1022285,1002877,1703278,0,1082233,0,0,0,0",
    "benji": "0,0,1054026,0,0,1006289,1703382,0,1082787,0,0,0,0",
    "study": "0,0,1053651,0,1022285,1005015,0,0,1082000,0,0,0,0",
    "pq": "1072369,0,1053791,0,1022073,1002798,1492026,1032061,1082232,0,0,0,0",
}

# 0:shoes, 1:, 2: Overall, 3: Face accessory, 4: Eye accessory, 5: Hat, 6: Weapon, 7: Earrings, 8: Gloves, 9: Cape

class Dress(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def outfit_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Provides outfit name suggestions while typing."""
        return [
            app_commands.Choice(name=key, value=key)
            for key in OUTFIT_PRESETS.keys()
            if current.lower() in key.lower()
        ][:25]  # Discord limits choices to 25 items

    @app_commands.command(
        name="dress", description="Dresses up the selected character with special outfits"
    )
    @app_commands.autocomplete(outfit=outfit_autocomplete)
    async def dress_character(
        self, interaction: discord.Interaction, ign: str, outfit: str
    ):
        if outfit not in OUTFIT_PRESETS:
            await interaction.response.send_message(
                f"❌ Invalid outfit! Available outfits: {', '.join(OUTFIT_PRESETS.keys())}",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        
        # Check if the outfit is valid
        if outfit.casefold() not in (key.casefold() for key in OUTFIT_PRESETS):
            await interaction.followup.send(
                f"❌ Invalid outfit! Available outfits: {', '.join(OUTFIT_PRESETS.keys())}",
                ephemeral=True,
            )
            return

        
        # Construct the base URL for the character
        base_url = f"https://dreamms.gg/?stats={ign}"
        try:
            response = requests.get(base_url)
            response.raise_for_status()  # Raise an exception for HTTP errors
        except requests.RequestException as e:
            await interaction.followup.send(f"Failed to retrieve character data: {e}", ephemeral=True)
            return
        
        # Parse the HTML content
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the correct <img> tag for the character image
        img_tag = soup.find('img', {'src': lambda x: x and 'api.dreamms.gg' in x})
        if not img_tag:
            await interaction.followup.send("Character image not found.", ephemeral=True)
            return
        
        # Decode the image URL
        encoded_url = img_tag['src']
        decoded_url = urllib.parse.unquote(encoded_url)  # Decode URL encoding
        print(f"Decoded URL: {decoded_url}")  # Debug print
        
        # Extract the skin ID and items part from the URL
        parts = decoded_url.split("/")
        skin_id = parts[7]  # The skin ID is the 8th part of the URL
        items_part = parts[8].rstrip(",")  # Remove trailing commas
        print(f"Skin ID: {skin_id}")  # Debug print
        print(f"Items part: {items_part}")  # Debug print
        
        # Split the items part into individual values
        items = items_part.split(",")
        print(f"Items: {items}")  # Debug print
        
        # Ensure the items part has exactly 13 values
        if len(items) != 13:
            await interaction.followup.send("Unexpected character data format.", ephemeral=True)
            return
        
        # Apply the selected outfit (excluding the last 2 values)
        outfit_values = OUTFIT_PRESETS[outfit.lower()].split(",")
        if len(outfit_values) != 13:
            await interaction.followup.send("Invalid outfit preset format.", ephemeral=True)
            return
        
        # Replace the relevant parts of the items with the outfit preset (excluding the last 2 values)
        updated_items = outfit_values[:-2] + items[-2:]
        print(f"Updated items: {updated_items}")  # Debug print
        
        # Construct the new character URL
        new_character_url = (
            f"https://api.dreamms.gg/api/gms/latest/character/animated/{skin_id}/{','.join(updated_items)}/walk1/"
            f"&renderMode=Centered&resize=1.gif"
        )
        print(f"New character URL: {new_character_url}")  # Debug print
        
        # Send the result as an embed
        embed = discord.Embed(title=f"{ign} dressed as {outfit.capitalize()}!")
        embed.set_image(url=new_character_url)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Dress(bot))