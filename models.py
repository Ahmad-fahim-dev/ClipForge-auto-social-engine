import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database with all tables."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            youtube_url TEXT NOT NULL,
            channel_id TEXT NOT NULL UNIQUE,
            thumbnail_url TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            last_checked TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            youtube_video_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            thumbnail_url TEXT DEFAULT '',
            published_at TEXT DEFAULT '',
            downloaded INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            file_path TEXT DEFAULT '',
            duration INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            thumbnail_path TEXT DEFAULT '',
            duration REAL DEFAULT 0,
            start_time REAL DEFAULT 0,
            end_time REAL DEFAULT 0,
            width INTEGER DEFAULT 1080,
            height INTEGER DEFAULT 1920,
            status TEXT DEFAULT 'ready',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            caption TEXT DEFAULT '',
            scheduled_at TEXT DEFAULT '',
            posted_at TEXT DEFAULT '',
            post_url TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (clip_id) REFERENCES clips(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL UNIQUE,
            username TEXT DEFAULT '',
            connected INTEGER DEFAULT 0,
            session_data TEXT DEFAULT '{}',
            channel_url TEXT DEFAULT '',
            api_key TEXT DEFAULT '',
            last_used TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            level TEXT DEFAULT 'info',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # Insert default settings if they don't exist
    defaults = {
        "check_interval": "10",
        "clips_per_video": "5",
        "clip_min_duration": "25",
        "clip_max_duration": "59",
        "post_delay": "30",
        "auto_post": "false",
        "auto_download": "true",
        "auto_clip": "true",
    }
    for key, value in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    # Insert default platform accounts
    for platform in ["youtube", "tiktok", "instagram"]:
        cursor.execute(
            "INSERT OR IGNORE INTO accounts (platform) VALUES (?)",
            (platform,)
        )

    conn.commit()
    conn.close()


def log_activity(action, details="", level="info"):
    """Log an activity event."""
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_log (action, details, level) VALUES (?, ?, ?)",
        (action, details, level)
    )
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    """Get a setting value."""
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    """Set a setting value."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_stats():
    """Get dashboard statistics."""
    conn = get_db()
    stats = {
        "total_channels": conn.execute("SELECT COUNT(*) FROM channels WHERE active=1").fetchone()[0],
        "total_videos": conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
        "total_clips": conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0],
        "total_posts": conn.execute("SELECT COUNT(*) FROM posts WHERE status='posted'").fetchone()[0],
        "queued_posts": conn.execute("SELECT COUNT(*) FROM posts WHERE status='queued'").fetchone()[0],
        "pending_downloads": conn.execute("SELECT COUNT(*) FROM videos WHERE downloaded=0").fetchone()[0],
        "pending_processing": conn.execute("SELECT COUNT(*) FROM videos WHERE downloaded=1 AND processed=0").fetchone()[0],
        "posts_today": conn.execute(
            "SELECT COUNT(*) FROM posts WHERE status='posted' AND date(posted_at)=date('now')"
        ).fetchone()[0],
    }
    conn.close()
    return stats
