import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables (e.g., your bot token)
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# Ensure TOKEN is not None for debugging purposes
if TOKEN is None:
    print("Error: DISCORD_BOT_TOKEN is not set in the .env file or environment variables.")
    exit()

# Enable intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent for commands
intents.voice_states = True     # Essential for music bot functionality
intents.guilds = True           # Required for guild-specific operations

bot = commands.Bot(command_prefix="!", intents=intents)

# Sync the command tree
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')
    await bot.tree.sync() # Sync global application commands
    print(f'Synced commands: {len(bot.tree.get_commands())} global commands.')
    
    # --- MODIFICATION START ---
    # List of specific cogs to load from the 'cogs' folder
    # Add all your actual cog filenames here (without the .py extension)
    # The music_cog.py is the primary one for music functionality
    # You also have 'clone', 'welcome', 'welcomeraw', 'dress' based on your traceback
    
    cogs_to_load = [
        "music_cog",
        "clone",
        "welcome",
        "welcomeraw",
        "dress",
        # Add any other cogs you might have here
    ]

    print(f"Loading specific cogs from 'cogs' folder:")
    for cog_name_base in cogs_to_load:
        cog_path = f"cogs.{cog_name_base}" # e.g., "cogs.music_cog"
        try:
            print(f"Loading cog: {cog_path}")
            await bot.load_extension(cog_path)
        except Exception as e:
            print(f"Failed to load cog {cog_path}: {e}")
            import traceback
            traceback.print_exc()
    # --- MODIFICATION END ---
            
    print('------')


# Define a simple slash command (if you want to keep it)
@bot.tree.command(name="hello", description="Say hello!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello!")

# Run the bot
async def main():
    # The cogs are now loaded in on_ready, so no explicit load_extensions call here.
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())