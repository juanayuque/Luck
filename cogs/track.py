import discord
import random
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="track", description="Gives a weekly comparison of a tracked character")
    await interaction.response.defer()  # Defer the response to avoid timeout
       

# Required setup function for cogs
async def setup(bot):
    await bot.add_cog(General(bot))
