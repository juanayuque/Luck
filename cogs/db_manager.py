import aiosqlite
from datetime import datetime, timezone
import traceback
# --- UPDATED IMPORT ---
from . import config # Import config from the same 'cogs' package parent
# ----------------------

class DBManager:
    def __init__(self):
        # DB_PATH is now loaded from the config, which is at the root
        self.db_path = config.DB_PATH

    async def initialize_db(self):
        """Initializes the SQLite database tables and indices."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                
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
                        url TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_downloaded_songs_url 
                    ON downloaded_songs(url)
                ''')
                await db.execute('''
                    CREATE INDEX IF NOT EXISTS idx_playlist_guild 
                    ON playlist(guild_id)
                ''')

                # Add 'last_played' column if it doesn't exist (for older databases)
                try:
                    await db.execute('ALTER TABLE downloaded_songs ADD COLUMN last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
                except aiosqlite.OperationalError as e:
                    if "duplicate column name" not in str(e):
                        raise # Re-raise if it's not the expected "duplicate column" error
                    pass
                        
                await db.commit()
            print("Database initialized successfully.")
        except Exception as e:
            print(f"Database initialization failed: {str(e)}")
            traceback.print_exc()

    async def get_all_songs(self):
        """Retrieves all unique downloaded songs, ordered by last played."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT id, title, url, MAX(last_played) 
                FROM downloaded_songs 
                GROUP BY url 
                ORDER BY last_played DESC
            ''')
            return await cursor.fetchall()

    async def get_songs_by_ids(self, song_ids: list):
        """Retrieves specific downloaded songs by their IDs."""
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ','.join('?' * len(song_ids))
            cursor = await db.execute(f'''
                SELECT url, title 
                FROM downloaded_songs 
                WHERE id IN ({placeholders})
            ''', song_ids)
            return await cursor.fetchall()

    async def add_to_playlist(self, guild_id: str, url: str, title: str):
        """Adds a song to the guild's playlist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT INTO playlist (guild_id, url, title)
                VALUES (?, ?, ?)
            ''', (guild_id, url, title))
            await db.commit()

    async def get_next_song_in_playlist(self, guild_id: str):
        """Retrieves the next song from the guild's playlist."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT url, title 
                FROM playlist 
                WHERE guild_id = ? 
                ORDER BY id ASC LIMIT 1
            ''', (guild_id,))
            return await cursor.fetchone()

    async def remove_from_playlist(self, guild_id: str, url: str):
        """Removes a song from the guild's playlist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM playlist WHERE guild_id = ? AND url = ?', (guild_id, url))
            await db.commit()

    async def clear_playlist(self, guild_id: str):
        """Clears the entire playlist for a given guild."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM playlist WHERE guild_id = ?', (guild_id,))
            await db.commit()

    async def get_cached_song_filename(self, url: str):
        """Retrieves the filename of a cached song by its URL."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT filename FROM downloaded_songs WHERE url = ?', (url,))
            return await cursor.fetchone()

    async def update_cached_song_timestamp(self, url: str):
        """Updates the last_played timestamp for a cached song."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE downloaded_songs SET last_played = ? WHERE url = ?', 
                             (datetime.now(timezone.utc), url))
            await db.commit()

    async def upsert_downloaded_song(self, guild_id: str, url: str, title: str, filename: str):
        """Inserts or updates a downloaded song record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT INTO downloaded_songs (guild_id, url, title, filename, last_played)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    last_played = excluded.last_played,
                    filename = excluded.filename,
                    title = excluded.title -- Update title in case it changed/was missing
            ''', (guild_id, url, title, filename, datetime.now(timezone.utc)))
            await db.commit()
            
    async def get_playlist_queue(self, guild_id: str):
        """Retrieves the entire playlist queue for a given guild."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT title, url FROM playlist 
                WHERE guild_id = ? 
                ORDER BY id
            ''', (guild_id,))
            return await cursor.fetchall()