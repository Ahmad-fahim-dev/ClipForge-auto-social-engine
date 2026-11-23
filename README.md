# ClipForge — Auto Social Engine

AI-powered social media automation system built in Python that tracks YouTube creators, downloads new uploads, transcribes them with Whisper, uses an LLM to find the most viral moments, cuts them into 9:16 short-form clips with AI-generated titles, hooks, captions and hashtags, and posts them to YouTube Shorts, TikTok, and Instagram Reels.

---

## Features

* **Creator Monitoring** — tracks YouTube channels via RSS feeds (no API key needed)
* **Auto Download** — yt-dlp pulls new uploads automatically
* **Whisper Transcription** — full speech-to-text with timestamps (API or local `faster-whisper`)
* **AI Viral Clip Detection** — an LLM ranks transcript segments by viral potential; cut points snap to natural speech boundaries
* **Smart Video Processing** — FFmpeg 9:16 center-crop to 1080×1920, thumbnails generated per clip
* **AI Metadata Generation** — optimized title, hook, caption and hashtags per platform (YouTube / TikTok / Instagram limits respected)
* **Multi-platform Auto Posting** — YouTube Data API, Selenium automation for TikTok/Instagram
* **Full Automation** — APScheduler background pipeline with a web dashboard for control
* **Graceful Degradation** — with no AI key configured, the engine falls back to scene-detection clip selection and template captions

---

## System Architecture

```
                ┌────────────────────┐
                │  YouTube Channels  │
                └─────────┬──────────┘
                          │ RSS polling (engine/monitor.py)
                          ▼
                ┌────────────────────┐
                │ Upload Detection   │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Video Downloader   │  yt-dlp (engine/downloader.py)
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Whisper Transcript │  engine/transcriber.py
                │ (API or local)     │  cached in DB `transcripts` table
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ AI Clip Detection  │  engine/ai_selector.py
                │ viral-moment rank  │  (fallback: ffprobe scene detection)
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Video Processing   │  engine/clipper.py
                │ 9:16 crop 1080×1920│  ffmpeg
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Metadata Generator │  engine/ai_content.py
                │ title/hook/caption │  (fallback: templates)
                └─────────┬──────────┘
                          │
                          ▼
        ┌──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼
 YouTube Shorts     TikTok        Instagram Reels
 (Data API v3)    (Selenium)      (Selenium)
```

---

## AI Pipeline Configuration

Open **Settings → AI Pipeline** in the dashboard (or use the REST API / env vars).

| Setting | Values | Notes |
|---|---|---|
| AI Pipeline | on / off | Master switch; off = classic heuristic pipeline |
| Provider | `openai` / `anthropic` | `openai` works with any OpenAI-compatible endpoint |
| API Key | string | Env fallback: `CLIPFORGE_AI_API_KEY` |
| Base URL | URL (optional) | e.g. `https://api.groq.com/openai/v1`, `http://localhost:11434/v1` (Ollama) |
| Chat Model | string | e.g. `gpt-4o-mini`, `llama-3.3-70b-versatile`, `claude-3-5-haiku-latest` |
| AI Metadata | on / off | Auto-generate title/hook/caption/hashtags when clips are created |
| Whisper Mode | `auto` / `api` / `local` | `api` uploads audio to an OpenAI-compatible endpoint; `local` runs faster-whisper on this machine |
| Whisper Model | `tiny`…`large-v3` | Local model size; API mode maps these to `whisper-1` |

Env-var fallbacks: `CLIPFORGE_AI_PROVIDER`, `CLIPFORGE_AI_API_KEY`, `CLIPFORGE_AI_BASE_URL`, `CLIPFORGE_AI_MODEL`, `CLIPFORGE_SECRET`. Settings-table values take precedence when set.

### API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/ai/status` | GET | AI configuration & capabilities (key never echoed) |
| `/api/ai/test` | POST | Live connectivity test |
| `/api/ai/generate/<clip_id>` | POST | (Re)generate title/hook/caption/hashtags for a clip (`{"platform": "tiktok"}`) |

---

## Tech Stack

* **Python 3.10+**, Flask 3, Jinja2
* **SQLite** (WAL) via `models.py`
* **FFmpeg / ffprobe** — clip extraction, 9:16 crop, thumbnails, scene detection
* **yt-dlp** — downloads
* **faster-whisper** — local speech-to-text (optional; API mode needs no local model)
* **Any OpenAI-compatible LLM API or Anthropic Claude** — clip selection & metadata
* **APScheduler** — background automation
* **Selenium** — TikTok / Instagram upload automation
* **YouTube Data API v3** — Shorts upload

---

## Project Structure

```
ClipForge-auto-social-engine/
├── app.py                     # Flask app + dashboard routes
├── config.py                  # paths, defaults, AI defaults
├── models.py                  # SQLite schema, settings, activity log
├── requirements.txt
├── routes/
│   └── api.py                 # REST API (channels/videos/clips/posts/accounts/AI/settings)
├── engine/
│   ├── monitor.py             # YouTube RSS channel monitoring
│   ├── downloader.py          # yt-dlp downloads
│   ├── transcriber.py         # Whisper transcription (API/local, cached)
│   ├── ai_client.py           # LLM client (OpenAI-compatible + Anthropic)
│   ├── ai_selector.py         # LLM viral-moment selection + validation
│   ├── ai_content.py          # LLM hooks/titles/captions/hashtags
│   ├── clipper.py             # clip extraction (9:16, 1080×1920)
│   ├── poster.py              # YouTube API + Selenium posting
│   └── scheduler.py           # APScheduler background jobs
├── templates/                 # dashboard pages (Jinja2)
└── static/                    # CSS/JS/assets
```

---

## Workflow

1. Monitor selected YouTube channels (RSS, every N minutes)
2. Detect new uploads
3. Download the video (yt-dlp, ≤1080p)
4. Transcribe with Whisper (API or local — cached per video)
5. LLM ranks the transcript and picks the most viral segments (25–59s default)
6. Cut clips with FFmpeg: 9:16 center crop, 1080×1920, AAC audio, thumbnail
7. Generate optimized title, hook, caption and hashtags per platform
8. Post manually from the dashboard or automatically on a schedule
9. Review results in the activity log and post queue

---

## Getting Started

Prerequisites: Python 3.10+, FFmpeg + ffprobe on PATH, a Chrome install (for Selenium posting).

```bash
git clone https://github.com/Ahmad-fahim-dev/ClipForge-auto-social-engine.git
cd ClipForge-auto-social-engine
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`:

1. **Channels** — add a YouTube channel (URL with `channel/UC...` ID)
2. **Accounts** — connect YouTube (API key), TikTok / Instagram (username + session)
3. **Settings → AI Pipeline** — choose a provider, paste an API key, hit *Test AI Connection*
4. **Videos** — download, then *Process* to generate AI-selected clips
5. **Clips** — preview, tweak or regenerate the AI caption, queue posts

No AI key? Everything still works — clip selection falls back to scene detection and captions use templates.

---

## Permissions & Compliance

* Only use content from creators with explicit permission
* Apply transformations (cropping, captions, edits)
* Follow each platform's automation and reposting policies
* Respect YouTube's Terms of Service when downloading

---

## Future Improvements

* Burned-in subtitles from Whisper timestamps
* AI voice commentary integration
* Retention-based re-ranking from posted-clip analytics
* Native TikTok / Instagram publish APIs

---

## Contributing

Contributions are welcome. Open an issue or submit a pull request.

## License

MIT License
