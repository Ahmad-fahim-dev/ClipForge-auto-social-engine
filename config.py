import os

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
SECRET_KEY = os.environ.get("CLIPFORGE_SECRET", "clipforge-secret-key-change-me")
DEBUG = True
HOST = "0.0.0.0"
PORT = 5000

# ─── AI Pipeline ─────────────────────────────────────────────────────────
# ClipForge talks to any OpenAI-compatible chat API (OpenAI, Groq, OpenRouter,
# DeepSeek, Ollama, LM Studio, ...) or the native Anthropic (Claude) API.
# Credentials live in the settings table; environment variables are a fallback.
AI_PROVIDERS = ("openai", "anthropic")
AI_DEFAULT_PROVIDER = "openai"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
AI_DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-3-5-haiku-latest"
AI_REQUEST_TIMEOUT = 90            # seconds for chat calls
AI_TRANSCRIBE_TIMEOUT = 900        # seconds for audio transcription uploads

# Whisper speech-to-text (local sizes: tiny/base/small/medium/large-v3)
WHISPER_DEFAULT_MODE = "auto"      # auto | api | local
WHISPER_DEFAULT_MODEL = "base"
WHISPER_LOCAL_SIZES = ("tiny", "base", "small", "medium", "large-v3")

# Env-var fallbacks (explicit settings-table values take precedence)
AI_ENV_KEYS = {
    "provider": "CLIPFORGE_AI_PROVIDER",
    "api_key": "CLIPFORGE_AI_API_KEY",
    "base_url": "CLIPFORGE_AI_BASE_URL",
    "model": "CLIPFORGE_AI_MODEL",
}
