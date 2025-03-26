import discord
from discord import app_commands
import yt_dlp as youtube_dl
import asyncio
import aiosqlite
import os
import random
import sys
import traceback
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
        try:
            print(f"[YTDL] Starting download for {url}")
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]
            
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            print(f"[YTDL] Successfully processed: {data.get('title')}")
            return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, filename=filename)
        except Exception as e:
            print(f"[YTDL] Error processing {url}: {str(e)}")
            traceback.print_exc()
            raise

class MusicPlayer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._setup_logging()
        # Removed the loop.create_task call from here

    async def setup_hook(self):
        """Async initialization"""
        await self.init_db()

    def _setup_logging(self):
        """Configure logging for VPS"""
        self.log_file = 'music_bot.log'
        print(f"Logging initialized. Output will be saved to {self.log_file}")

    async def init_db(self):
        """Initialize database with error handling"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Enable foreign key support
                await db.execute("PRAGMA foreign_keys = ON")
                
                # Create tables if they don't exist
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
                        last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Try to add missing columns if they don't exist
                try:
                    await db.execute('ALTER TABLE downloaded_songs ADD COLUMN last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
                except aiosqlite.OperationalError:
                    pass  # Column already exists
                    
                await db.commit()
        except Exception as e:
            print(f"Database initialization failed: {str(e)}")
            traceback.print_exc()

    async def log(self, message):
        """Log messages to file and console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)
        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')

    @commands.command()
    async def play(self, ctx, url):
        """Play audio from YouTube with enhanced debugging"""
        await self.log(f"Play command invoked by {ctx.author} in {ctx.guild.name} with URL: {url}")

        try:
            guild_id = str(ctx.guild.id)

            # Voice channel checks with debugging
            if ctx.author.voice is None:
                await self.log("User not in voice channel")
                return await ctx.send("You are not in a voice channel.")

            await self.log(f"User in voice channel: {ctx.author.voice.channel}")

            # Voice client handling
            if ctx.voice_client is None:
                await self.log("Connecting to voice channel...")
                channel = ctx.author.voice.channel
                await channel.connect()
                await self.log(f"Connected to {channel}")
            elif ctx.voice_client.channel != ctx.author.voice.channel:
                await self.log(f"Moving from {ctx.voice_client.channel} to {ctx.author.voice.channel}")
                await ctx.voice_client.move_to(ctx.author.voice.channel)

            # Download and play with detailed logging
            async with ctx.typing():
                try:
                    if ctx.voice_client.is_playing():
                        delay = random.randint(7, 15)
                        await self.log(f"Already playing, waiting {delay} seconds")
                        await asyncio.sleep(delay)
                    
                    await self.log(f"Starting download for {url}")
                    player = await YTDLSource.from_url(url, loop=self.bot.loop)
                    song_title = player.title
                    filename = player.filename
                    await self.log(f"Downloaded: {song_title} (File: {filename})")

                except youtube_dl.utils.DownloadError as e:
                    error_msg = f"YouTube DL Error: {str(e)}"
                    await self.log(error_msg)
                    if '429' in str(e):
                        return await ctx.send("⚠️ YouTube is rate-limiting the bot. Try again later.")
                    elif '403' in str(e):
                        return await ctx.send("🚫 Access denied (403). This video may be restricted.")
                    else:
                        return await ctx.send(f"❌ Download error: {str(e)}")

            # Database and playback handling
            async with aiosqlite.connect(DB_PATH) as db:
                if ctx.voice_client.is_playing():
                    await self.log(f"Adding to queue: {song_title}")
                    await db.execute('INSERT INTO playlist (guild_id, url, title) VALUES (?, ?, ?)', 
                                    (guild_id, url, song_title))
                    await db.commit()
                    await self.show_playlist(ctx, new_song=song_title)
                else:
                    await self.log(f"Starting playback: {song_title}")
                    ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(ctx), self.bot.loop))
                    await ctx.send(f'▶️ Now playing: **{song_title}**')

            await self.store_downloaded_song(ctx, url, song_title, filename)

        except Exception as e:
            error_msg = f"Critical error in play command: {type(e).__name__}: {str(e)}"
            await self.log(error_msg)
            traceback.print_exc()
            await ctx.send(f"🔥 Critical error occurred: {str(e)}")

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
    cog = MusicPlayer(bot)
    await cog.setup_hook()  # Call the async setup
    await bot.add_cog(cog)