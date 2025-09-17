<<<<<<< HEAD
import os
import asyncio
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ---------- Env & logging ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")  # optional: fast per-guild sync while developing

if not TOKEN:
    raise SystemExit("Error: DISCORD_BOT_TOKEN is not set in .env or environment.")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("luck.bot")

# ---------- Intents ----------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# List the cogs you actually have in ./cogs (without .py)
COGS_TO_LOAD = [
    "music_cog",
    "clone",
    "welcome",
    "welcomeraw",
    "dress",
    # add more here
]

async def load_cogs():
    """Load all extensions in COGS_TO_LOAD from the cogs package."""
    for name in COGS_TO_LOAD:
        ext = f"cogs.{name}"
        try:
            log.info(f"Loading extension: %s", ext)
            await bot.load_extension(ext)
        except Exception as e:
            log.exception("Failed to load %s: %s", ext, e)

async def sync_commands():
    """Sync app commands. If DEV_GUILD_ID is set, do a fast per-guild sync."""
    if DEV_GUILD_ID:
        guild = discord.Object(id=int(DEV_GUILD_ID))
        synced = await bot.tree.sync(guild=guild)
        log.info("Synced %d guild commands to guild %s", len(synced), DEV_GUILD_ID)
    else:
        synced = await bot.tree.sync()
        log.info("Synced %d global commands", len(synced))

    # Log the command list
    all_cmds = bot.tree.get_commands() if not DEV_GUILD_ID else bot.tree.get_commands(guild=discord.Object(id=int(DEV_GUILD_ID)))
    names = ", ".join(sorted(cmd.qualified_name for cmd in all_cmds))
    log.info("Available slash commands: %s", names or "(none)")

# ---------- Lifecycle ----------

@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)

@bot.event
async def setup_hook():
    # Runs before the bot connects; perfect for loading cogs and syncing once.
    await load_cogs()
    await sync_commands()

# ---------- Utility commands ----------

=======
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
>>>>>>> ea3573f54e1cfc10898f49c986e9d69a733a7cdb
@bot.tree.command(name="hello", description="Say hello!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello!")

<<<<<<< HEAD
@bot.tree.command(name="commands", description="List all available slash commands.")
async def list_commands(interaction: discord.Interaction):
    # For per-guild dev sync, list that guild’s view; otherwise global view
    cmds = bot.tree.get_commands() if not DEV_GUILD_ID else bot.tree.get_commands(guild=interaction.guild)
    lines = [f"/{cmd.qualified_name} — {cmd.description or 'No description'}" for cmd in sorted(cmds, key=lambda c: c.qualified_name)]
    text = "\n".join(lines) or "No slash commands are registered."
    await interaction.response.send_message(f"**Slash commands ({len(lines)}):**\n{text}", ephemeral=True)

@bot.command(name="commands", help="List all available slash commands (DM to you).")
async def list_commands_text(ctx: commands.Context):
    cmds = bot.tree.get_commands()
    lines = [f"/{cmd.qualified_name} — {cmd.description or 'No description'}" for cmd in sorted(cmds, key=lambda c: c.qualified_name)]
    text = "\n".join(lines) or "No slash commands are registered."
    try:
        await ctx.author.send(f"Slash commands ({len(lines)}):\n{text}")
        if ctx.guild:
            await ctx.reply("I DM’d you the list of slash commands.", mention_author=False)
    except discord.Forbidden:
        await ctx.reply("I couldn't DM you. Enable DMs from server members.", mention_author=False)

# ---------- Run ----------

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
=======
# Run the bot
async def main():
    # The cogs are now loaded in on_ready, so no explicit load_extensions call here.
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
>>>>>>> ea3573f54e1cfc10898f49c986e9d69a733a7cdb
