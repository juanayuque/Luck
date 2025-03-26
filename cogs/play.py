import discord
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
import aiosqlite
import os
import random
from datetime import datetime
from discord.ext import commands

# Configuration
DB_PATH = 'database.db'
SONGS_DIR = 'songs'
os.makedirs(SONGS_DIR, exist_ok=True)

# YouTube DL options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': f'{SONGS_DIR}/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {'options': '-vn'}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.filename = filename

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, filename=filename)

class MusicPlayer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.init_db())

    async def init_db(self):
        """Initialize the database tables"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS downloaded_songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    last_played TIMESTAMP NOT NULL
                )
            ''')
            await db.commit()

    # Slash command version
    @app_commands.command(name="play", description="Play audio from YouTube")
    async def play_slash(self, interaction: discord.Interaction, url: str):
        """Slash command to play audio"""
        await interaction.response.defer()
        ctx = await commands.Context.from_interaction(interaction)
        await self._play(ctx, url)

    # Prefix command version
    @commands.command(name="play")
    async def play_prefix(self, ctx, *, url: str):
        """Prefix command to play audio"""
        await self._play(ctx, url)

    # Common play logic
    async def _play(self, ctx, url):
        """Shared play functionality for both command types"""
        guild_id = str(ctx.guild.id)

        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return

        if ctx.voice_client is None:
            channel = ctx.author.voice.channel
            await channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)

        async with ctx.typing():
            try:
                if ctx.voice_client.is_playing():
                    delay = random.randint(7, 15)
                    print(f"Waiting {delay} seconds before downloading the song...")
                    await asyncio.sleep(delay)
                
                player = await YTDLSource.from_url(url, loop=self.bot.loop)
            except youtube_dl.utils.DownloadError as e:
                if '429' in str(e):
                    await ctx.send("⚠️ YouTube is rate-limiting the bot. Try again later.")
                elif '403' in str(e):
                    await ctx.send("🚫 Access denied (403). This video may be restricted or unavailable.")
                else:
                    await ctx.send(f"❌ Error: {str(e)}")
                return

            song_title = player.title
            filename = player.filename

        async with aiosqlite.connect(DB_PATH) as db:
            if ctx.voice_client.is_playing():
                await db.execute('INSERT INTO playlist (guild_id, url, title) VALUES (?, ?, ?)', 
                                (guild_id, url, song_title))
                await db.commit()
                await self.show_playlist(ctx, new_song=song_title)
            else:
                ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
                await ctx.send(f'▶️ Now playing: **{song_title}**')

        await self.store_downloaded_song(ctx, url, song_title, filename)

    # Slash command version
    @app_commands.command(name="queue", description="Show the current playlist")
    async def queue_slash(self, interaction: discord.Interaction):
        """Slash command to show queue"""
        ctx = await commands.Context.from_interaction(interaction)
        await self.show_playlist(ctx)

    # Prefix command version
    @commands.command(name="queue")
    async def queue_prefix(self, ctx):
        """Prefix command to show queue"""
        await self.show_playlist(ctx)

    async def show_playlist(self, ctx, new_song=None):
        """Show the current playlist"""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT title FROM playlist WHERE guild_id = ? ORDER BY id', (str(ctx.guild.id),))
            queue = await cursor.fetchall()
        
        if queue:
            message = "**Current Queue:**\n" + "\n".join(f"{i+1}. {title}" for i, (title,) in enumerate(queue))
        else:
            message = "The queue is empty."
        
        await ctx.send(message)

    # Slash command version
    @app_commands.command(name="leave", description="Leave the voice channel")
    async def leave_slash(self, interaction: discord.Interaction):
        """Slash command to leave voice"""
        ctx = await commands.Context.from_interaction(interaction)
        await self._leave(ctx)

    # Prefix command version
    @commands.command(name="leave")
    async def leave_prefix(self, ctx):
        """Prefix command to leave voice"""
        await self._leave(ctx)

    # Common leave logic
    async def _leave(self, ctx):
        """Shared leave functionality"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Left the voice channel.")

    # Other methods remain the same (play_next, store_downloaded_song, etc.)

async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))