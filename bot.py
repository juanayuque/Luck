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

@bot.tree.command(name="hello", description="Say hello!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello!")

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
