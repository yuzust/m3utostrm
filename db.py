import sqlite3
import os
import json
from datetime import datetime
import aiosqlite
import asyncio
import logging


# Database file path
DB_FILE = 'data/m3u_converter.db'

# Ensure data directory exists
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

# Create tables if they don't exist
def init_db():
    """Initialize the database with required tables"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Config table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        ''')
        
        # M3U links table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS m3u_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            output_path TEXT,
            last_check TEXT,
            next_check TEXT,
            update_frequency INTEGER DEFAULT 24
        )
        ''')
        
        # Content tracking table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            url TEXT,
            content_type TEXT NOT NULL,
            action TEXT NOT NULL,
            item_name TEXT NOT NULL,
            details TEXT
        )
        ''')
        
        conn.commit()

# Initialize the database on module import
init_db()

# Config functions
def save_config(config_dict):
    """Save configuration dictionary to database"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Convert complex values to JSON strings
        for key, value in config_dict.items():
            if isinstance(value, (list, dict, bool)):
                value = json.dumps(value)
            cursor.execute(
                'INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)',
                (key, value)
            )
        
        conn.commit()

def load_config():
    """Load configuration from database or return defaults"""
    default_config = {
        "output_path": "content",
        "movie_keywords": ["movie", "film", "feature", "cinema"],
        "tv_keywords": [
            "tv", "show", "series", "episode", "season", "s01", "s02", "e01", "e02",
            "television", "sitcom", "drama series", "miniseries", "documentary series"
        ],
        "log_level": "NORMAL",
        "language_filter": "EN",
        "skip_non_english": True,
        "update_frequency": 24,
        "ui_theme": "dark",
        "discord_webhook_url": "",
        "notifications_enabled": False
    }
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT key, value FROM config')
        rows = cursor.fetchall()
        
        if not rows:
            # No config found, save and return defaults
            save_config(default_config)
            return default_config
            
        # Build config from database
        config = {}
        for row in rows:
            key, value = row['key'], row['value']
            
            # Try to parse JSON for complex types
            try:
                if value.startswith('[') or value.startswith('{'):
                    config[key] = json.loads(value)
                elif value.lower() == 'true':
                    config[key] = True
                elif value.lower() == 'false':
                    config[key] = False
                elif value.isdigit():
                    config[key] = int(value)
                else:
                    config[key] = value
            except (json.JSONDecodeError, AttributeError):
                config[key] = value
                
        # Ensure all default keys exist
        for key, value in default_config.items():
            if key not in config:
                config[key] = value
                
        return config

# M3U links functions
def save_m3u_link(url, filename, output_path=None, update_frequency=None):
    """Save M3U link to database with better error handling"""
    try:
        if update_frequency is None:
            config = load_config()
            update_frequency = config.get("update_frequency", 24)
            
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT OR REPLACE INTO m3u_links 
                   (url, filename, output_path, last_check, update_frequency) 
                   VALUES (?, ?, ?, ?, ?)''',
                (url, filename, output_path, now, update_frequency)
            )
            conn.commit()
            
        # Verify the link was saved
        saved_links = load_m3u_links()
        for link in saved_links:
            if link['url'] == url:
                return True
                
        # If we got here, the link wasn't found after saving
        raise Exception("Link was not saved successfully")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error saving M3U link: {str(e)}")
        raise

def update_m3u_link_next_check(url, next_check):
    """Update the next check time for an M3U link"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE m3u_links SET next_check = ? WHERE url = ?',
            (next_check, url)
        )
        conn.commit()

def update_m3u_link_last_check(url):
    """Update the last check time for an M3U link to now"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE m3u_links SET last_check = ? WHERE url = ?',
            (now, url)
        )
        conn.commit()

def load_m3u_links():
    """Load all M3U links from database with better error handling"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM m3u_links')
            rows = cursor.fetchall()
            
            links = []
            for row in rows:
                links.append(dict(row))
                
            return links
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error loading M3U links: {str(e)}")
        # Return empty list instead of raising to avoid cascading errors
        return []

def remove_m3u_link(url):
    """Remove an M3U link from database"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM m3u_links WHERE url = ?', (url,))
        conn.commit()
        return cursor.rowcount > 0

# Content tracking functions
def log_content_change(content_type, action, item_name, url=None, details=None):
    """Log a content change to the database"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details_json = json.dumps(details) if details else None
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO content_history 
               (timestamp, url, content_type, action, item_name, details) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (now, url, content_type, action, item_name, details_json)
        )
        conn.commit()

def get_recent_content_changes(limit=100):
    """Get recent content changes"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM content_history ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()
        
        changes = []
        for row in rows:
            change = dict(row)
            if change['details']:
                try:
                    change['details'] = json.loads(change['details'])
                except json.JSONDecodeError:
                    pass
            changes.append(change)
            
        return changes

def get_content_stats():
    """Get statistics about content changes"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get counts by type and action
        cursor.execute('''
            SELECT content_type, action, COUNT(*) as count 
            FROM content_history 
            GROUP BY content_type, action
        ''')
        
        stats = {}
        for row in cursor.fetchall():
            content_type = row['content_type']
            action = row['action']
            count = row['count']
            
            if content_type not in stats:
                stats[content_type] = {}
                
            stats[content_type][action] = count
            
        return stats

# Async versions of key functions
async def async_save_m3u_link(url, filename, output_path=None, update_frequency=None):
    """Async version of save_m3u_link"""
    if update_frequency is None:
        config = load_config()
        update_frequency = config.get("update_frequency", 24)
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            '''INSERT OR REPLACE INTO m3u_links 
               (url, filename, output_path, last_check, update_frequency) 
               VALUES (?, ?, ?, ?, ?)''',
            (url, filename, output_path, now, update_frequency)
        )
        await conn.commit()

async def async_load_m3u_links():
    """Async version of load_m3u_links"""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute('SELECT * FROM m3u_links')
        rows = await cursor.fetchall()
        
        links = []
        for row in rows:
            links.append(dict(row))
            
        return links

async def async_update_m3u_link_next_check(url, next_check):
    """Async version of update_m3u_link_next_check"""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            'UPDATE m3u_links SET next_check = ? WHERE url = ?',
            (next_check, url)
        )
        await conn.commit()

async def async_update_m3u_link_last_check(url):
    """Async version of update_m3u_link_last_check"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            'UPDATE m3u_links SET last_check = ? WHERE url = ?',
            (now, url)
        )
        await conn.commit()

async def async_log_content_change(content_type, action, item_name, url=None, details=None):
    """Async version of log_content_change"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details_json = json.dumps(details) if details else None
    
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            '''INSERT INTO content_history 
               (timestamp, url, content_type, action, item_name, details) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (now, url, content_type, action, item_name, details_json)
        )
        await conn.commit()

# Function to migrate from JSON to SQLite (if needed)
def migrate_from_json():
    """Migrate data from JSON files to SQLite database"""
    # Migrate config
    config_file = 'data/config.json'
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                save_config(config)
                print(f"Migrated configuration from {config_file}")
        except Exception as e:
            print(f"Error migrating config: {str(e)}")
    
    # Migrate M3U links
    links_file = 'data/m3u_links.json'
    if os.path.exists(links_file):
        try:
            with open(links_file, 'r') as f:
                links = json.load(f)
                for link in links:
                    save_m3u_link(
                        link['url'], 
                        link['filename'], 
                        link.get('output_path'),
                        link.get('update_frequency', 24)
                    )
                print(f"Migrated {len(links)} M3U links from {links_file}")
        except Exception as e:
            print(f"Error migrating links: {str(e)}")

# Run migration on import if needed
if (not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0) and (
    os.path.exists('data/config.json') or os.path.exists('data/m3u_links.json')):
    print("Database is empty but JSON files exist. Running migration...")
    migrate_from_json()