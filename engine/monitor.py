"""
Channel Monitor — polls YouTube RSS feeds for new video uploads.
"""
import feedparser
import re
import requests
from datetime import datetime
from models import get_db, log_activity
from config import YT_RSS_TEMPLATE


def extract_channel_id(url):
    """Extract channel ID from various YouTube URL formats."""
    # Direct channel ID
    match = re.search(r'channel/(UC[\w-]{22})', url)
    if match:
        return match.group(1)

    # From RSS feed URL
    match = re.search(r'channel_id=(UC[\w-]{22})', url)
    if match:
        return match.group(1)

    # Try to resolve @handle or /c/ URLs
    if "/@" in url or "/c/" in url or "/user/" in url:
        try:
            resp = requests.get(url, timeout=10)
            match = re.search(r'"channelId":"(UC[\w-]{22})"', resp.text)
            if match:
                return match.group(1)
            match = re.search(r'channel/(UC[\w-]{22})', resp.text)
            if match:
                return match.group(1)
        except Exception:
            pass

    return None


def get_channel_info(channel_id):
    """Get basic channel info from the RSS feed."""
    feed_url = YT_RSS_TEMPLATE.format(channel_id=channel_id)
    feed = feedparser.parse(feed_url)
    if feed.feed.get("title"):
        return {
            "name": feed.feed.get("title", "Unknown Channel"),
            "channel_id": channel_id,
            "thumbnail_url": "",
        }
    return None


def check_channel(channel_id_db, yt_channel_id):
    """Check a single channel for new videos."""
    feed_url = YT_RSS_TEMPLATE.format(channel_id=yt_channel_id)
    feed = feedparser.parse(feed_url)
    new_videos = []

    conn = get_db()
    for entry in feed.entries:
        yt_video_id = entry.get("yt_videoid", "")
        if not yt_video_id:
            link = entry.get("link", "")
            match = re.search(r'v=([\w-]{11})', link)
            yt_video_id = match.group(1) if match else ""

        if not yt_video_id:
            continue

        title = entry.get("title", "Untitled")

        # Skip Shorts
        if "#shorts" in title.lower():
            continue

        # Check if already in DB
        existing = conn.execute(
            "SELECT id FROM videos WHERE youtube_video_id = ?", (yt_video_id,)
        ).fetchone()
        if existing:
            continue

        video_url = f"https://www.youtube.com/watch?v={yt_video_id}"
        thumbnail = f"https://img.youtube.com/vi/{yt_video_id}/maxresdefault.jpg"
        published = entry.get("published", "")

        conn.execute(
            """INSERT INTO videos (channel_id, youtube_video_id, title, url, thumbnail_url, published_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (channel_id_db, yt_video_id, title, video_url, thumbnail, published)
        )
        new_videos.append({"title": title, "url": video_url, "id": yt_video_id})

    # Update last_checked
    conn.execute(
        "UPDATE channels SET last_checked = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), channel_id_db)
    )
    conn.commit()
    conn.close()

    return new_videos


def check_all_channels():
    """Check all active channels for new videos."""
    conn = get_db()
    channels = conn.execute(
        "SELECT id, channel_id FROM channels WHERE active = 1"
    ).fetchall()
    conn.close()

    total_new = 0
    for ch in channels:
        try:
            new_vids = check_channel(ch["id"], ch["channel_id"])
            if new_vids:
                total_new += len(new_vids)
                for v in new_vids:
                    log_activity(
                        "New Video Detected",
                        f"{v['title']} — {v['url']}",
                        "success"
                    )
        except Exception as e:
            log_activity("Monitor Error", f"Channel {ch['channel_id']}: {str(e)}", "error")

    if total_new > 0:
        log_activity("Monitor Scan Complete", f"Found {total_new} new video(s)", "info")

    return total_new
