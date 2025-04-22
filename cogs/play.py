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
DB_PATH = 'database.db'  # This creates a proper path for your OS
SONGS_DIR = 'songs'
os.makedirs(SONGS_DIR, exist_ok=True)

# YouTube DL options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': 'songs/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'cookiefile': 'cookies.txt',
    'sleep_interval': 5,  # Minimum wait of 5 seconds
    'max_sleep_interval': 10,  # Maximum wait of 15 seconds
    'throttled-rate': '10000K',  # Limit download speed to 100 KB/s
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
        self.song_list_messages = {}  # Track song list messages

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
        self.queue_messages = {}  # Track queue messages per guild
        self.song_list_messages = {}  # For tracking song list messages

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.id in self.queue_messages.values():
            guild_id = next((k for k, v in self.queue_messages.items() if v == message.id), None)
            if guild_id:
                del self.queue_messages[guild_id]
        
        if message.id in self.song_list_messages.values():
            guild_id = next((k for k, v in self.song_list_messages.items() if v == message.id), None)
            if guild_id:
                del self.song_list_messages[guild_id]

    async def setup_hook(self):
        """Async initialization"""
        await self.init_db()

    def _setup_logging(self):
        """Configure logging for VPS"""
        self.log_file = 'music_bot.log'
        # Ensure the file is created with UTF-8 encoding
        with open(self.log_file, 'a', encoding='utf-8') as f:
            pass  # Just create/clear the file
        print(f"Logging initialized. Output will be saved to {self.log_file}")

    async def init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_downloaded_songs_url 
                ON downloaded_songs(url)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_playlist_guild 
                ON playlist(guild_id)
            ''')
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
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
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_msg + '\n')
        except Exception as e:
            print(f"Failed to write to log file: {str(e)}")

    @commands.command()
    async def songs(self, ctx):
        """List all unique songs in the database"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Get unique songs sorted by most recently played
                cursor = await db.execute('''
                    SELECT id, title, url, MAX(last_played) 
                    FROM downloaded_songs 
                    GROUP BY url 
                    ORDER BY last_played DESC
                ''')
                songs = await cursor.fetchall()
            
            if not songs:
                return await ctx.send("No songs found in the database.")
            
            # Create paginated embeds
            pages = []
            chunk_size = 10
            for i in range(0, len(songs), chunk_size):
                embed = discord.Embed(
                    title="🎶 Song Library",
                    description="All available songs (use `!playsongs ID` to queue)",
                    color=0x2b2d31
                )
                
                for song in songs[i:i+chunk_size]:
                    song_id, title, url, _ = song
                    embed.add_field(
                        name=f"{song_id}. {title}",
                        value=f"[YouTube Link]({url})",
                        inline=False
                    )
                
                embed.set_footer(text=f"Page {i//chunk_size + 1}/{(len(songs)-1)//chunk_size + 1}")
                pages.append(embed)
            
            # Send first page with navigation buttons
            message = await ctx.send(embed=pages[0])
            self.song_list_messages[ctx.guild.id] = message
            
            # Add navigation buttons if multiple pages
            if len(pages) > 1:
                view = discord.ui.View(timeout=60)
                
                prev_button = discord.ui.Button(style=discord.ButtonStyle.blurple, emoji="⬅️")
                next_button = discord.ui.Button(style=discord.ButtonStyle.blurple, emoji="➡️")
                
                async def paginate(interaction, direction):
                    current_page = next(
                        (i for i, page in enumerate(pages) 
                        if page.title == interaction.message.embeds[0].title), 0)
                    new_page = max(0, min(len(pages)-1, current_page + direction))
                    
                    await interaction.response.edit_message(
                        embed=pages[new_page])
                
                prev_button.callback = lambda i: paginate(i, -1)
                next_button.callback = lambda i: paginate(i, 1)
                
                view.add_item(prev_button)
                view.add_item(next_button)
                await message.edit(view=view)
        
        except Exception as e:
            await ctx.send(f"❌ Error listing songs: {str(e)}")
            traceback.print_exc()

    @commands.command()
    async def playsongs(self, ctx, *args):
        """Queue multiple songs by ID or 'all'"""
        if not args:
            return await self.update_queue_message(ctx, force_new=True)
        
        # Check if user is in a voice channel
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel to use this command.")

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                if args[0].lower() == 'all':
                    # Queue all songs from database
                    cursor = await db.execute('''
                        SELECT url, title 
                        FROM downloaded_songs 
                        GROUP BY url 
                        ORDER BY last_played DESC
                    ''')
                    songs = await cursor.fetchall()
                    
                    if not songs:
                        return await ctx.send("No songs found in the database.")
                    
                    queued_count = 0
                    for url, title in songs:
                        await db.execute('''
                            INSERT INTO playlist (guild_id, url, title)
                            VALUES (?, ?, ?)
                        ''', (str(ctx.guild.id), url, title))
                        queued_count += 1
                    
                    await db.commit()
                    await ctx.send(f"✅ Queued all {queued_count} songs!")
                
                else:
                    # Queue specific song IDs
                    song_ids = [int(arg) for arg in args if arg.isdigit()]
                    if not song_ids:
                        return await ctx.send("Please provide valid song IDs.")
                    
                    placeholders = ','.join('?' * len(song_ids))
                    cursor = await db.execute(f'''
                        SELECT url, title 
                        FROM downloaded_songs 
                        WHERE id IN ({placeholders})
                    ''', song_ids)
                    songs = await cursor.fetchall()
                    
                    if len(songs) != len(song_ids):
                        return await ctx.send("Some song IDs were not found.")
                    
                    for url, title in songs:
                        await db.execute('''
                            INSERT INTO playlist (guild_id, url, title)
                            VALUES (?, ?, ?)
                        ''', (str(ctx.guild.id), url, title))
                    
                    await db.commit()
                    await ctx.send(f"✅ Queued {len(songs)} songs!")
                
                await self.update_queue_message(ctx, force_new=True)
                
                if not ctx.voice_client:
                    await ctx.author.voice.channel.connect()
                
                if not ctx.voice_client.is_playing():
                    await self.play_next(ctx)
        
        except ValueError:
            await ctx.send("Please provide valid numeric song IDs.")
        except Exception as e:
            await ctx.send(f"❌ Error creating playlist: {str(e)}")
            traceback.print_exc()

    @commands.command()
    async def play(self, ctx, url):
        """Play audio from YouTube with enhanced debugging"""
        await self.log(f"Play command invoked by {ctx.author} in {ctx.guild.name} with URL: {url}")

        try:
            guild_id = str(ctx.guild.id)

            # Voice channel checks
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

            # Use a single database connection for the entire operation
            async with aiosqlite.connect(DB_PATH) as db:
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode=WAL")
                
                # Check cache first
                cursor = await db.execute('SELECT filename FROM downloaded_songs WHERE url = ?', (url,))
                cached = await cursor.fetchone()
                
                if cached and os.path.exists(cached[0]):
                    await self.log(f"Using cached file for {url}")
                    filename = cached[0]
                    # Update last_played timestamp
                    await db.execute('UPDATE downloaded_songs SET last_played = ? WHERE url = ?', 
                                (datetime.utcnow(), url))
                    await db.commit()
                    
                    # Extract info without downloading
                    data = await self.bot.loop.run_in_executor(None, 
                        lambda: ytdl.extract_info(url, download=False))
                    player = YTDLSource(discord.FFmpegPCMAudio(filename, **ffmpeg_options), 
                                data=data, filename=filename)
                    song_title = player.title
                else:
                    # Only download if not in cache
                    async with ctx.typing():
                        if ctx.voice_client.is_playing():
                            delay = random.randint(7, 15)
                            await self.log(f"Already playing, waiting {delay} seconds")
                            await asyncio.sleep(delay)
                        
                        await self.log(f"Downloading {url} (not in cache)")
                        player = await YTDLSource.from_url(url, loop=self.bot.loop)
                        song_title = player.title
                        filename = player.filename
                        await db.execute('INSERT INTO downloaded_songs (guild_id, url, title, filename, last_played) VALUES (?, ?, ?, ?, ?)',
                                    (guild_id, url, song_title, filename, datetime.utcnow()))
                        await db.commit()

                # Playback handling
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

        except Exception as e:
            error_msg = f"Critical error in play command: {type(e).__name__}: {str(e)}"
            await self.log(error_msg)
            traceback.print_exc()
            await ctx.send(f"🔥 Critical error occurred: {str(e)}")

    async def play_next(self, ctx):
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute('''
                        SELECT url, title 
                        FROM playlist 
                        WHERE guild_id = ? 
                        ORDER BY id ASC LIMIT 1
                    ''', (str(ctx.guild.id),))
                    next_song = await cursor.fetchone()

                    if not next_song:
                        await ctx.send("📭 Queue is empty.")
                        return

                    url, title = next_song

                    # Fetch local file info
                    cursor = await db.execute('SELECT filename FROM downloaded_songs WHERE url = ?', (url,))
                    result = await cursor.fetchone()

                    if result and os.path.exists(result[0]):
                        filename = result[0]
                        await db.execute('DELETE FROM playlist WHERE guild_id = ? AND url = ?', (str(ctx.guild.id), url))
                        await db.commit()

                        # Create player using local file
                        source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
                        player = YTDLSource(source, data={"title": title}, filename=filename)

                        ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                            self.play_next(ctx), self.bot.loop))

                        await ctx.send(f"▶️ Now playing from cache: **{title}**")
                    else:
                        await ctx.send(f"❌ Local file not found for {title}. Skipping...")
                        await db.execute('DELETE FROM playlist WHERE guild_id = ? AND url = ?', (str(ctx.guild.id), url))
                        await db.commit()
                        await self.play_next(ctx)

            except Exception as e:
                await ctx.send(f"❌ Error playing next song: {str(e)}")
                traceback.print_exc()



    async def update_queue_message(self, ctx, force_new=False):
        """Update or resend the queue message with interactive buttons"""
        async with aiosqlite.connect(DB_PATH) as db:
            # Get current playing song if any
            current_title = None
            if ctx.voice_client and ctx.voice_client.is_playing():
                cursor = await db.execute('''
                    SELECT title FROM playlist 
                    WHERE guild_id = ? 
                    ORDER BY id LIMIT 1
                ''', (str(ctx.guild.id),))
                current = await cursor.fetchone()
                current_title = current[0] if current else None
            
            # Get full queue
            cursor = await db.execute('''
                SELECT title, url FROM playlist 
                WHERE guild_id = ? 
                ORDER BY id
            ''', (str(ctx.guild.id),))
            queue = await cursor.fetchall()
        
        embed = discord.Embed(title="🎵 Current Queue", color=0x2b2d31)
        
        if current_title:
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{current_title}**",
                inline=False
            )
        
        if queue:
            queue_list = "\n".join(
                f"`{i+1}.` [{title}]({url})" 
                for i, (title, url) in enumerate(queue[1:] if current_title else queue)
            )
            
            if queue_list:
                embed.add_field(
                    name="Up Next" if current_title else "Queue",
                    value=queue_list[:1024],
                    inline=False
                )
            
            if len(queue) > (11 if current_title else 10):
                embed.set_footer(text=f"+ {len(queue)-(11 if current_title else 10)} more songs")
        else:
            embed.description = "The queue is currently empty."
        
        view = discord.ui.View(timeout=180)
        
        if queue:
            skip_btn = discord.ui.Button(style=discord.ButtonStyle.blurple, label="⏭️ Skip")
            skip_btn.callback = lambda i: self.skip_current(i)
            view.add_item(skip_btn)
            
            clear_btn = discord.ui.Button(style=discord.ButtonStyle.red, label="🗑️ Clear")
            clear_btn.callback = lambda i: self.clear_queue(i)
            view.add_item(clear_btn)
        
        # Message management
        if not hasattr(self, 'queue_messages'):
            self.queue_messages = {}
        
        # Always send new message if forced or no existing message
        if force_new or ctx.guild.id not in self.queue_messages:
            try:
                if ctx.guild.id in self.queue_messages:
                    await self.queue_messages[ctx.guild.id].delete()
            except:
                pass
            
            msg = await ctx.send(embed=embed, view=view)
            self.queue_messages[ctx.guild.id] = msg
        else:
            try:
                await self.queue_messages[ctx.guild.id].edit(embed=embed, view=view)
            except discord.NotFound:
                msg = await ctx.send(embed=embed, view=view)
                self.queue_messages[ctx.guild.id] = msg

    async def skip_current(self, interaction):
        """Skip current song button handler"""
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message("⏭️ Skipped current song", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is currently playing", ephemeral=True)

    async def clear_queue(self, interaction):
        """Clear queue button handler"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'DELETE FROM playlist WHERE guild_id = ?',
                (str(interaction.guild.id),)
            )
            await db.commit()
        
        await interaction.response.send_message("🗑️ Queue cleared", ephemeral=True)
        await self.update_queue_message(interaction)

    async def show_playlist(self, ctx, new_song=None):
        """Show the current playlist (now handled by update_queue_message)"""
        await self.update_queue_message(ctx)

    async def store_downloaded_song(self, ctx, url, title, filename):
        """Store the downloaded song for future use"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Upsert operation - update if exists, insert if not
                await db.execute('''
                    INSERT INTO downloaded_songs (guild_id, url, title, filename, last_played)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        last_played = excluded.last_played,
                        filename = excluded.filename
                ''', (str(ctx.guild.id), url, title, filename, datetime.utcnow()))
                await db.commit()
        except Exception as e:
            await self.log(f"Error storing song: {str(e)}")
            traceback.print_exc()

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