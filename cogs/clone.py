import discord
import requests
import urllib.parse
from bs4 import BeautifulSoup
from discord.ext import commands

class Clone(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="cloneoutfit", description="Clone the outfit from another character")
    async def clone_outfit(self, interaction: discord.Interaction, ign: str, target_ign: str):
        await interaction.response.defer()
        
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
        print(f"Decoded URL (Base Character): {decoded_url}")  # Debug print
        
        # Extract the skin ID and items part from the URL
        parts = decoded_url.split("/")
        skin_id = parts[7]  # The skin ID is the 8th part of the URL
        items_part = parts[8].rstrip(",")  # Remove trailing commas
        print(f"Skin ID (Base Character): {skin_id}")  # Debug print
        print(f"Items part (Base Character): {items_part}")  # Debug print
        
        # Split the items part into individual values
        base_items = items_part.split(",")
        print(f"Base Items: {base_items}")  # Debug print
        
        # Ensure the items part has exactly 13 values
        if len(base_items) != 13:
            await interaction.followup.send("Unexpected character data format.", ephemeral=True)
            return
        
        # Construct the target URL for the character to copy from
        target_url = f"https://dreamms.gg/?stats={target_ign}"
        try:
            target_response = requests.get(target_url)
            target_response.raise_for_status()  # Raise an exception for HTTP errors
        except requests.RequestException as e:
            await interaction.followup.send(f"Failed to retrieve target character data: {e}", ephemeral=True)
            return
        
        # Parse the HTML content for the target character
        target_soup = BeautifulSoup(target_response.content, 'html.parser')
        
        # Find the correct <img> tag for the target character image
        target_img_tag = target_soup.find('img', {'src': lambda x: x and 'api.dreamms.gg' in x})
        if not target_img_tag:
            await interaction.followup.send("Target character image not found.", ephemeral=True)
            return
        
        # Decode the target image URL
        target_encoded_url = target_img_tag['src']
        target_decoded_url = urllib.parse.unquote(target_encoded_url)  # Decode URL encoding
        print(f"Decoded URL (Target Character): {target_decoded_url}")  # Debug print
        
        # Extract the items part from the target URL
        target_parts = target_decoded_url.split("/")
        target_items_part = target_parts[8].rstrip(",")  # Remove trailing commas
        print(f"Items part (Target Character): {target_items_part}")  # Debug print
        
        # Split the target items part into individual values
        target_items = target_items_part.split(",")
        print(f"Target Items: {target_items}")  # Debug print
        
        # Ensure the target items part has exactly 13 values
        if len(target_items) != 13:
            await interaction.followup.send("Unexpected target character data format.", ephemeral=True)
            return
        
        # Replace the relevant parts of the base items with the target items (excluding the last 2 values)
        updated_items = target_items[:-2] + base_items[-2:]
        print(f"Updated items: {updated_items}")  # Debug print
        
        # Construct the new character URL
        new_character_url = (
            f"https://api.dreamms.gg/api/gms/latest/character/animated/{skin_id}/{','.join(updated_items)}/walk1/"
            f"&renderMode=Centered&resize=1.gif"
        )
        print(f"New character URL: {new_character_url}")  # Debug print
        
        # Send the result as an embed
        embed = discord.Embed(title=f"{ign} cloned outfit from {target_ign}!")
        embed.set_image(url=new_character_url)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Clone(bot))
    print("Clone cog loaded")