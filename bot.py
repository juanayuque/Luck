import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv # Import load_dotenv

# Load environment variables (e.g., your bot token)
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN') # Get token from .env

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
    
    # Load all cogs (command files) from the cogs folder
    cogs_folder = os.path.join(os.path.dirname(__file__), "cogs")
    print(f"Loading cogs from: {cogs_folder}")
    for filename in os.listdir(cogs_folder):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = f"cogs.{filename[:-3]}"
            try:
                print(f"Loading cog: {cog_name}")
                await bot.load_extension(cog_name)
            except Exception as e:
                print(f"Failed to load cog {cog_name}: {e}")
                import traceback
                traceback.print_exc()
    print('------')


# Define a simple slash command (if you want to keep it)
@bot.tree.command(name="hello", description="Say hello!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello!")

# Run the bot
async def main():
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())