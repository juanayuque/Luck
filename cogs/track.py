import discord
import random
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

       

# Required setup function for cogs
async def setup(bot):
    await bot.add_cog(General(bot))
