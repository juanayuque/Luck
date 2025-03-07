import discord
import random
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def roll(self, ctx, max_roll: int = 100):
        """Rolls a random number between 0 and max_roll"""
        if max_roll < 1:
            await ctx.send("Please provide a positive integer for the roll.")
            return

        roll_result = random.randint(0, max_roll)
        await ctx.send(f"You rolled a {roll_result} (0-{max_roll}).")

# Required setup function for cogs
async def setup(bot):
    await bot.add_cog(General(bot))
