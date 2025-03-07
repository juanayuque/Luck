import discord
from discord.ext import commands

class Content(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="content", description="Choose a game and get a random content")
    async def content(self, ctx):
        select = discord.ui.Select(
            options=[
                discord.SelectOption(label="Dream", value="DreamMS"),
                discord.SelectOption(label="Reboot", value="Reboot"),
                discord.SelectOption(label="IRL", value="IRL"),
            ]
        )
        await ctx.send("Choose a game:", view=select)

async def setup(bot):
    await bot.add_cog(Content(bot))
