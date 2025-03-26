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

    async def cog_unload(self):
        for vc in self.bot.voice_clients:
            await vc.disconnect()

    @commands.command()
    async def play(self, ctx, url):
        """Play audio from YouTube"""
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
                await db.execute('INSERT INTO playlist (guild_id, url, title) VALUES (?, ?, ?)', (guild_id, url, song_title))
                await db.commit()
                await self.show_playlist(ctx, new_song=song_title)
            else:
                ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
                await ctx.send(f'▶️ Now playing: **{song_title}**')

        await self.store_downloaded_song(ctx, url, song_title, filename)

    async def play_next(self, ctx):
        """Play the next song in the queue"""
        voice_client = ctx.voice_client
        if not voice_client:
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT url, title FROM playlist WHERE guild_id = ? ORDER BY id LIMIT 1', (str(ctx.guild.id),))
            next_song = await cursor.fetchone()
            
            if next_song:
                url, title = next_song
                await db.execute('DELETE FROM playlist WHERE url = ?', (url,))
                await db.commit()
                
                player = await YTDLSource.from_url(url, loop=self.bot.loop)
                voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
                await ctx.send(f"▶️ Now playing: **{title}**")

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

    async def store_downloaded_song(self, ctx, url, title, filename):
        """Store the downloaded song for future use"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO downloaded_songs (guild_id, url, title, filename, last_played) VALUES (?, ?, ?, ?, ?)',
                             (str(ctx.guild.id), url, title, filename, datetime.utcnow()))
            await db.commit()

    @commands.command()
    async def leave(self, ctx):
        """Leave the voice channel"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Left the voice channel.")

async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))