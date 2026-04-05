import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Database
DATABASE_PATH = os.path.join(BASE_DIR, "clipforge.db")

# Media Directories
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")
THUMBNAILS_DIR = os.path.join(BASE_DIR, "thumbnails")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

# Create directories if they don't exist
for d in [DOWNLOADS_DIR, CLIPS_DIR, THUMBNAILS_DIR, SESSIONS_DIR]:
    os.makedirs(d, exist_ok=True)

# Defaults
DEFAULT_CHECK_INTERVAL = 10        # minutes between RSS checks
DEFAULT_CLIPS_PER_VIDEO = 5        # clips to extract per video
DEFAULT_CLIP_MIN_DURATION = 25     # seconds
DEFAULT_CLIP_MAX_DURATION = 59     # seconds (under 60 for Shorts)
DEFAULT_POST_DELAY = 30            # minutes between auto-posts
DEFAULT_AUTO_POST = False          # auto-post off by default

# YouTube RSS feed template
YT_RSS_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# Video download settings
MAX_VIDEO_RESOLUTION = "1080"
DOWNLOAD_FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"

# Flask
SECRET_KEY = os.environ.get("CLIPFORGE_SECRET_KEY", secrets.token_hex(32))
DEBUG = os.environ.get("CLIPFORGE_DEBUG", "true").lower() == "true"
HOST = "0.0.0.0"
PORT = 5000
