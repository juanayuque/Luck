import discord
from discord.ext import commands
import os
from config import TOKEN  # Store your bot token in config.py
import asyncio

# Enable intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix="!", intents=intents)

# Sync the command tree
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user.name}')
    print(f'Synced commands: {bot.tree.get_commands()}')
    for command in bot.tree.get_commands():
        print(f'Command: {command.name}')

# Define a simple slash command
@bot.tree.command(name="hello", description="Say hello!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello!")

# Load all cogs (command files) from the cogs folder
async def load_extensions():
    cogs_folder = os.path.join(os.path.dirname(__file__), "cogs")
    print(f"Loading cogs from: {cogs_folder}")
    for filename in os.listdir(cogs_folder):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = f"cogs.{filename[:-3]}"
            print(f"Loading cog: {cog_name}")
            await bot.load_extension(cog_name)

# Run the bot
async def main():
    await load_extensions()
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())