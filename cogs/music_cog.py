import discord
from discord.ext import commands
import asyncio
import os
import random
import traceback
from datetime import datetime, timezone

# --- UPDATED IMPORTS FOR COGS PACKAGE STRUCTURE ---
from . import config           # Import config from the same 'cogs' package parent
from .ytdl_utils import YTDLSource  # Import YTDLSource from ytdl_utils.py within 'cogs'
from .db_manager import DBManager # Import DBManager from db_manager.py within 'cogs'
# --------------------------------------------------

class MusicPlayer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_manager = DBManager() # Initialize DBManager
        self._setup_logging()
        self.queue_messages = {}  # Track queue messages per guild
        self.song_list_messages = {}  # For tracking song list messages

        # MusicPlayer's own YTDL instance (recommended for consistency)
        # Still references GLOBAL_YTDL from config, which is now imported relatively
        self.ytdl_instance = config.GLOBAL_YTDL 

    async def setup_hook(self):
        """Async initialization for the cog, called after bot is ready."""
        await self.db_manager.initialize_db()

    def _setup_logging(self):
        """Configures basic logging for the music bot."""
        self.log_file = 'music_bot.log' # Path relative to where main.py is run
        with open(self.log_file, 'a', encoding='utf-8') as f:
            pass  # Ensure the file exists
        print(f"Logging initialized. Output will be saved to {self.log_file}")

    async def log(self, message: str):
        """Logs messages to a file and console with a timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_msg + '\n')
        except Exception as e:
            print(f"Failed to write to log file: {str(e)}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Removes tracked messages if they are deleted."""
        if message.id in self.queue_messages.values():
            guild_id = next((k for k, v in self.queue_messages.items() if v == message.id), None)
            if guild_id:
                del self.queue_messages[guild_id]
        
        if message.id in self.song_list_messages.values():
            guild_id = next((k for k, v in self.song_list_messages.items() if v == message.id), None)
            if guild_id:
                del self.song_list_messages[guild_id]

    @commands.command()
    async def songs(self, ctx: commands.Context):
        """Lists all unique songs stored in the bot's library."""
        try:
            songs = await self.db_manager.get_all_songs()
            
            if not songs:
                return await ctx.send("No songs found in the database.")
            
            pages = []
            chunk_size = 10
            for i in range(0, len(songs), chunk_size):
                embed = discord.Embed(
                    title="🎶 Song Library",
                    description="All available songs (use `!playsongs ID` to queue)",
                    color=0x2b2d31
                )
                
                for song_id, title, url, _ in songs[i:i+chunk_size]:
                    embed.add_field(
                        name=f"{song_id}. {title}",
                        value=f"[YouTube Link]({url})",
                        inline=False
                    )
                
                embed.set_footer(text=f"Page {i//chunk_size + 1}/{(len(songs)-1)//chunk_size + 1}")
                pages.append(embed)
            
            message = await ctx.send(embed=pages[0])
            self.song_list_messages[ctx.guild.id] = message
            
            if len(pages) > 1:
                view = discord.ui.View(timeout=60)
                
                async def paginate_callback(interaction: discord.Interaction, direction: int):
                    current_page_index = 0
                    for i, page in enumerate(pages):
                        if interaction.message.embeds and page.title == interaction.message.embeds[0].title:
                            current_page_index = i
                            break

                    new_page_index = max(0, min(len(pages)-1, current_page_index + direction))
                    
                    await interaction.response.edit_message(embed=pages[new_page_index])
                
                prev_button = discord.ui.Button(style=discord.ButtonStyle.blurple, emoji="⬅️")
                prev_button.callback = lambda i: paginate_callback(i, -1)
                
                next_button = discord.ui.Button(style=discord.ButtonStyle.blurple, emoji="➡️")
                next_button.callback = lambda i: paginate_callback(i, 1)
                
                view.add_item(prev_button)
                view.add_item(next_button)
                await message.edit(view=view)
        
        except Exception as e:
            await ctx.send(f"❌ Error listing songs: {str(e)}")
            traceback.print_exc()

    @commands.command()
    async def playsongs(self, ctx: commands.Context, *args):
        """Queues songs by ID from the bot's library or all of them."""
        if not args:
            return await self.update_queue_message(ctx, force_new=True)
        
        if not ctx.author.voice:
            return await ctx.send("You need to be in a voice channel to use this command.")

        try:
            guild_id = str(ctx.guild.id)
            songs_to_queue = []

            if args[0].lower() == 'all':
                songs_to_queue = await self.db_manager.get_all_songs()
                if not songs_to_queue:
                    return await ctx.send("No songs found in the database.")
                # Format for playlist (url, title)
                songs_to_queue = [(s[2], s[1]) for s in songs_to_queue] 
                await ctx.send(f"✅ Queued all {len(songs_to_queue)} songs!")
            else:
                song_ids = [int(arg) for arg in args if arg.isdigit()]
                if not song_ids:
                    return await ctx.send("Please provide valid song IDs.")
                
                songs_to_queue = await self.db_manager.get_songs_by_ids(song_ids)
                
                if len(songs_to_queue) != len(song_ids):
                    await ctx.send("Some song IDs were not found.")
                await ctx.send(f"✅ Queued {len(songs_to_queue)} songs!")
            
            for url, title in songs_to_queue:
                await self.db_manager.add_to_playlist(guild_id, url, title)
            
            await self.update_queue_message(ctx, force_new=True)
            
            vc = ctx.voice_client
            if not vc:
                vc = await ctx.author.voice.channel.connect()

            if not vc or not vc.is_connected():
                await ctx.send("❌ Failed to connect to the voice channel.")
                return

            if not vc.is_playing():
                await self.play_next(ctx)
        
        except ValueError:
            await ctx.send("Please provide valid numeric song IDs.")
        except Exception as e:
            await ctx.send(f"❌ Error creating playlist: {str(e)}")
            traceback.print_exc()

    @commands.command()
    async def play(self, ctx: commands.Context, url: str):
        """Plays audio from a YouTube URL or adds it to the queue."""
        await self.log(f"Play command invoked by {ctx.author} in {ctx.guild.name} with URL: {url}")

        try:
            guild_id = str(ctx.guild.id)

            if ctx.author.voice is None:
                await self.log("User not in voice channel")
                return await ctx.send("You are not in a voice channel.")

            channel = ctx.author.voice.channel
            await self.log(f"User in voice channel: {channel}")
            vc = ctx.voice_client

            if vc is None:
                await self.log("Attempting to connect to voice channel...")
                try:
                    vc = await channel.connect()
                    await self.log(f"Successfully connected to {channel}")
                    
                    # --- NEW: Add a small delay and re-check connection ---
                    await asyncio.sleep(0.5) # Wait for half a second
                    if not vc.is_connected():
                        await self.log("DEBUG: Voice client immediately disconnected after connect(). Aborting.")
                        await ctx.send("❌ I connected briefly but then lost connection. Please try again.")
                        return
                    await self.log("DEBUG: Voice client still connected after 0.5s delay.")
                    # --- END NEW ---

                except (discord.ClientException, discord.Forbidden, discord.HTTPException) as e:
                    await ctx.send(f"❌ Failed to connect to voice channel: {e}")
                    await self.log(f"Error connecting: {e}")
                    return
                except Exception as e:
                    await ctx.send(f"❌ Unexpected error while connecting: {e}")
                    await self.log(f"Unexpected error during connect: {e}")
                    return
            else:
                if vc.channel != channel:
                    await self.log(f"Moving from {vc.channel} to {channel}")
                    await vc.move_to(channel)
                    # --- NEW: Add a small delay after move_to and re-check connection ---
                    await asyncio.sleep(0.5) # Wait for half a second
                    if not vc.is_connected():
                        await self.log("DEBUG: Voice client immediately disconnected after move_to(). Aborting.")
                        await ctx.send("❌ I moved channels but then lost connection. Please try again.")
                        return
                    await self.log("DEBUG: Voice client still connected after move_to and 0.5s delay.")
                    # --- END NEW ---


            # The existing check here is still good, but the one above is more immediate
            if not vc.is_connected():
                await self.log("DEBUG: Voice client reports NOT connected right before player creation (secondary check).")
                await ctx.send("❌ I connected, but then immediately lost connection. Please try again.")
                return

            song_title = None
            player = None
            filename = None # Initialize filename here

            cached_filename_result = await self.db_manager.get_cached_song_filename(url)

            if cached_filename_result and os.path.exists(cached_filename_result[0]):
                await self.log(f"Using cached file for {url}")
                filename = cached_filename_result[0] # Assign filename from cache
                await self.db_manager.update_cached_song_timestamp(url)
                
                # Extract info without downloading for metadata using this cog's YTDL instance
                data = await self.bot.loop.run_in_executor(None, 
                    lambda: self.ytdl_instance.extract_info(url, download=False))
                
                if data:
                    await self.log(f"DEBUG: Cached filename: {filename}")
                    if not os.path.exists(filename):
                        await self.log(f"ERROR: Cached file '{filename}' does not exist despite initial check.")
                        cached_filename_result = None # Force re-download
                    elif not os.access(filename, os.R_OK):
                        await self.log(f"ERROR: Cached file '{filename}' exists but is not readable.")
                        cached_filename_result = None # Force re-download
                    else:
                        await self.log(f"DEBUG: Cached file '{filename}' exists and is readable.")

                    if cached_filename_result: # Re-check if it's still valid after new checks
                        player = YTDLSource(discord.FFmpegPCMAudio(filename, **config.FFMPEG_OPTIONS), 
                                            data=data, filename=filename)
                        song_title = player.title
                else:
                    await self.log(f"Could not extract info for cached URL: {url}. Forcing re-download.")
                    cached_filename_result = None # Force download below
            
            # If not cached or cached data was invalid
            if not cached_filename_result:
                await ctx.send(f"Downloading {url}...")
                await self.log(f"Downloading {url} (not in cache or cache invalid)")
                
                async with ctx.typing():
                    if vc.is_playing(): 
                        delay = random.randint(7, 15)
                        await self.log(f"Already playing, waiting {delay} seconds before download.")
                        await asyncio.sleep(delay)
                    
                    player = await YTDLSource.from_url(url, loop=self.bot.loop, ytdl_instance=self.ytdl_instance)
                    song_title = player.title
                    filename = player.filename # Assign filename from new download
                    await self.db_manager.upsert_downloaded_song(guild_id, url, song_title, player.filename)

            if player is None:
                await self.log("ERROR: Player object is None after all attempts to create it.")
                await ctx.send("❌ Failed to prepare audio source. Cannot play this song.")
                return
            
            if not vc.is_connected(): # Check again right before playing
                await self.log("DEBUG: Voice client reports NOT connected right before vc.play(). (Final check)") # Renamed for clarity
                await ctx.send("❌ I lost connection right before trying to play. Please try again.")
                return

            if vc.is_playing(): 
                await self.log(f"Adding to queue: {song_title}")
                await self.db_manager.add_to_playlist(guild_id, url, song_title)
                await self.update_queue_message(ctx, new_song=song_title)
                await ctx.send(f'🎶 Added to queue: **{song_title}**')
            else:
                await self.log(f"Starting playback: {song_title}")
                try:
                    vc.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(ctx), self.bot.loop))
                    await self.log(f"DEBUG: Playback initiated successfully for {song_title} using file: {filename}")
                except Exception as play_error:
                    await self.log(f"ERROR: Exception during vc.play() for {song_title}: {play_error}")
                    traceback.print_exc()
                    await ctx.send(f"❌ Could not start playback: {play_error}")
                    if vc and vc.is_connected():
                        await self.log(f"DEBUG: Disconnecting due to playback error for {song_title}")
                        await vc.disconnect()
                    return
                await ctx.send(f'▶️ Now playing: **{song_title}**')

        except Exception as e:
            error_msg = f"Critical error in play command: {type(e).__name__}: {str(e)}"
            await self.log(error_msg)
            traceback.print_exc()
            await ctx.send(f"🔥 Critical error occurred: {str(e)}")

    async def play_next(self, ctx: commands.Context):
        """Plays the next song in the guild's queue."""
        try:
            guild_id = str(ctx.guild.id)
            next_song = await self.db_manager.get_next_song_in_playlist(guild_id)

            if not next_song:
                await ctx.send("📭 Queue is empty. Disconnecting...")
                if ctx.voice_client:
                    await ctx.voice_client.disconnect()
                return

            url, title = next_song
            cached_filename_result = await self.db_manager.get_cached_song_filename(url)

            if cached_filename_result and os.path.exists(cached_filename_result[0]):
                filename = cached_filename_result[0]
                await self.db_manager.remove_from_playlist(guild_id, url)

                source = discord.FFmpegPCMAudio(filename, **config.FFMPEG_OPTIONS)
                # Ensure data is passed correctly to YTDLSource for title access
                player = YTDLSource(source, data={"title": title, "url": url}, filename=filename) 

                ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx), self.bot.loop))

                await ctx.send(f"▶️ Now playing from cache: **{title}**")
                await self.update_queue_message(ctx)
            else:
                await ctx.send(f"❌ Local file not found for **{title}**. Attempting re-download...")
                await self.db_manager.remove_from_playlist(guild_id, url) # Remove missing file from playlist
                
                try:
                    # Attempt to re-download the missing file
                    # Use this cog's YTDL instance
                    new_player = await YTDLSource.from_url(url, loop=self.bot.loop, ytdl_instance=self.ytdl_instance)
                    
                    # Update DB with the new filename and timestamp
                    await self.db_manager.upsert_downloaded_song(guild_id, url, new_player.title, new_player.filename)

                    ctx.voice_client.play(new_player, after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(ctx), self.bot.loop))
                    await ctx.send(f"✅ Re-downloaded and now playing: **{new_player.title}**")
                    await self.update_queue_message(ctx)

                except Exception as download_e:
                    await ctx.send(f"❌ Failed to re-download **{title}**: {str(download_e)}. Skipping to next in queue.")
                    await self.log(f"Failed to re-download {title}: {str(download_e)}")
                    traceback.print_exc()
                    asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop) # Try next song

        except Exception as e:
            await ctx.send(f"❌ Error playing next song: {str(e)}")
            traceback.print_exc()

    async def update_queue_message(self, ctx: commands.Context, force_new: bool = False, new_song: str = None):
        """Updates or resends the interactive queue message for the guild."""
        current_title = None
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.voice_client.source:
            # If the current source is a YTDLSource, get its title
            if isinstance(ctx.voice_client.source, YTDLSource):
                current_title = ctx.voice_client.source.title
            else: # Fallback if for some reason it's not YTDLSource
                current_title = "Unknown Song"

        queue = await self.db_manager.get_playlist_queue(str(ctx.guild.id))
        
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
                for i, (title, url) in enumerate(queue)
            )
            
            if queue_list:
                embed.add_field(
                    name="Up Next" if current_title else "Queue",
                    value=queue_list[:1024],
                    inline=False
                )
            
            remaining_songs_count = len(queue)
            if remaining_songs_count > 10: # If more than 10 are in 'Up Next'
                embed.set_footer(text=f"+ {remaining_songs_count - 10} more songs")
        else:
            embed.description = "The queue is currently empty."
        
        view = discord.ui.View(timeout=180)
        
        if current_title or queue: # Only show buttons if something is playing or queued
            skip_btn = discord.ui.Button(style=discord.ButtonStyle.blurple, label="⏭️ Skip")
            skip_btn.callback = self._create_skip_callback() # Use helper to pass ctx
            view.add_item(skip_btn)
            
            clear_btn = discord.ui.Button(style=discord.ButtonStyle.red, label="🗑️ Clear")
            clear_btn.callback = self._create_clear_callback() # Use helper to pass ctx
            view.add_item(clear_btn)
        
        # Message management to either edit or send a new message
        if force_new or ctx.guild.id not in self.queue_messages:
            try:
                if ctx.guild.id in self.queue_messages and self.queue_messages[ctx.guild.id]:
                    await self.queue_messages[ctx.guild.id].delete()
            except discord.NotFound:
                pass # Message already deleted
            except Exception as e:
                await self.log(f"Error deleting old queue message: {e}")

            msg = await ctx.send(embed=embed, view=view)
            self.queue_messages[ctx.guild.id] = msg
        else:
            try:
                # Use edit_message_with_timeout for robustness
                await self._edit_message_with_timeout(self.queue_messages[ctx.guild.id], embed=embed, view=view)
            except discord.NotFound:
                # If message was deleted externally, send a new one
                msg = await ctx.send(embed=embed, view=view)
                self.queue_messages[ctx.guild.id] = msg
            except Exception as e:
                await self.log(f"Error editing queue message: {e}")
                # Fallback to sending a new message on unexpected edit errors
                msg = await ctx.send(embed=embed, view=view)
                self.queue_messages[ctx.guild.id] = msg

    # Helper function for editing messages with a timeout (to prevent rate limits)
    async def _edit_message_with_timeout(self, message: discord.Message, **kwargs):
        try:
            await asyncio.wait_for(message.edit(**kwargs), timeout=5.0)
        except asyncio.TimeoutError:
            self.log(f"Timeout editing message {message.id}. Might be rate limited.")
            raise # Re-raise to trigger fallback (sending new message)
            
    # Helper to create callbacks that retain 'self' and 'ctx'
    def _create_skip_callback(self):
        async def callback(interaction: discord.Interaction):
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_playing():
                voice_client.stop()
                await interaction.response.send_message("⏭️ Skipped current song", ephemeral=True)
            else:
                await interaction.response.send_message("Nothing is currently playing", ephemeral=True)
            # Update queue message after skipping
            mock_ctx = commands.Context(
                message=interaction.message,
                bot=self.bot,
                view=None, # Not relevant for this usage
                prefix='!', # Not relevant
                command=None # Not relevant
            )
            mock_ctx.guild = interaction.guild
            mock_ctx.channel = interaction.channel
            mock_ctx.author = interaction.user 
            await self.update_queue_message(mock_ctx, force_new=True)
        return callback

    def _create_clear_callback(self):
        async def callback(interaction: discord.Interaction):
            guild_id = str(interaction.guild.id)
            await self.db_manager.clear_playlist(guild_id)
            
            await interaction.response.send_message("🗑️ Queue cleared", ephemeral=True)
            # You might want to stop the current song if the queue is cleared
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_playing():
                voice_client.stop()
            
            mock_ctx = commands.Context(
                message=interaction.message,
                bot=self.bot,
                view=None, # Not relevant for this usage
                prefix='!', # Not relevant
                command=None # Not relevant
            )
            mock_ctx.guild = interaction.guild
            mock_ctx.channel = interaction.channel
            mock_ctx.author = interaction.user 
            
            await self.update_queue_message(mock_ctx, force_new=True) # Force new to ensure full refresh
        return callback


    @commands.command()
    async def leave(self, ctx: commands.Context):
        """Makes the bot leave the voice channel."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Left the voice channel.")
        else:
            await ctx.send("I'm not in a voice channel.")

# This function is required by discord.py to load the cog
async def setup(bot: commands.Bot):
    cog = MusicPlayer(bot)
    await cog.setup_hook()
    await bot.add_cog(cog)