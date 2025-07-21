import os
import yt_dlp as youtube_dl

# --- Directories & Database ---
# These paths are relative to your main bot script's execution location
DB_PATH = 'database.db'
SONGS_DIR = 'songs'
os.makedirs(SONGS_DIR, exist_ok=True) # Ensure songs directory exists

# --- YouTube DL Options ---
YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    # outtmpl path should also be relative to the bot's root or an absolute path
    'outtmpl': os.path.join(SONGS_DIR, '%(extractor)s-%(id)s-%(title)s.%(ext)s'),
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
    'sleep_interval': 5,
    'max_sleep_interval': 10,
    'throttled-rate': '10000K',
}

# --- FFmpeg Options ---
FFMPEG_OPTIONS = {'options': '-vn'}

# --- Global YTDL Instance (Fallback) ---
GLOBAL_YTDL = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)