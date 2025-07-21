import discord
import yt_dlp as youtube_dl
import asyncio
import traceback
# --- UPDATED IMPORT ---
from . import config # Import config from the same 'cogs' package parent
# ----------------------

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.filename = filename

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=False, ytdl_instance=None):
        """
        Creates a YTDLSource instance from a given URL.
        :param url: The URL to process.
        :param loop: The asyncio event loop.
        :param stream: Whether to stream the audio (True) or download it (False).
        :param ytdl_instance: An optional custom YoutubeDL instance to use.
                               Defaults to config.GLOBAL_YTDL if not provided.
        """
        loop = loop or asyncio.get_event_loop()
        
        # Use the provided ytdl_instance, or fallback to the global one from config
        _ytdl = ytdl_instance or config.GLOBAL_YTDL 

        try:
            print(f"[YTDL] Starting processing for {url}")
            data = await loop.run_in_executor(None, lambda: _ytdl.extract_info(url, download=not stream))
            
            if 'entries' in data:
                data = data['entries'][0]
            
            filename = data['url'] if stream else _ytdl.prepare_filename(data)
            print(f"[YTDL] Successfully processed: {data.get('title')}")
            
            # Use FFMPEG_OPTIONS from config
            return cls(discord.FFmpegPCMAudio(filename, **config.FFMPEG_OPTIONS), 
                       data=data, filename=filename)
        except Exception as e:
            print(f"[YTDL] Error processing {url}: {str(e)}")
            traceback.print_exc()
            raise # Re-raise the exception to be handled by the caller