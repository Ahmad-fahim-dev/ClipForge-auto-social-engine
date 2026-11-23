"""
Transcriber — Whisper speech-to-text for downloaded videos.

Three execution strategies (setting: whisper_mode = auto | api | local):
  api    → upload audio to an OpenAI-compatible /audio/transcriptions endpoint
           (OpenAI whisper-1, Groq whisper-large-v3, ...)
  local  → faster-whisper (preferred) or openai-whisper running on this machine
  auto   → try api first (when the provider is OpenAI-compatible), then local

Transcripts are cached in the `transcripts` table, keyed by video_id.
Every function degrades gracefully: on failure the caller falls back to
heuristic (scene-based) clip selection.
"""
import json
import os
import subprocess
import tempfile

import requests

from config import (
    AI_TRANSCRIBE_TIMEOUT,
    DOWNLOADS_DIR,
    WHISPER_LOCAL_SIZES,
)
from engine.ai_client import AIError, get_ai_config
from models import get_db, get_setting, log_activity

# OpenAI's audio endpoint accepts files up to 25 MB; keep a safety margin.
_API_SIZE_LIMIT = 20 * 1024 * 1024


def get_transcript(video_id):
    """Return the cached transcript for a video (dict) or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT language, text, segments, engine FROM transcripts WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        segments = json.loads(row["segments"] or "[]")
    except ValueError:
        segments = []
    return {
        "language": row["language"] or "",
        "text": row["text"] or "",
        "segments": segments,
        "engine": row["engine"] or "",
    }


def transcribe_video(video_id):
    """
    Transcribe a downloaded video with Whisper (cached after the first run).

    Returns {"language", "text", "segments": [{start, end, text}], "engine"}
    or None when transcription is unavailable/fails.
    """
    cached = get_transcript(video_id)
    if cached and cached.get("text", "").strip():
        return cached

    conn = get_db()
    video = conn.execute(
        "SELECT id, title, file_path FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    conn.close()
    if not video or not video["file_path"]:
        return None

    file_path = video["file_path"]
    if not os.path.exists(file_path):
        local = os.path.join(DOWNLOADS_DIR, os.path.basename(file_path))
        if os.path.exists(local):
            file_path = local
        else:
            return None

    mode = str(get_setting("whisper_mode", "auto")).lower()
    result = None

    if mode in ("auto", "api"):
        result = _transcribe_via_api(file_path)
        if result is None and mode == "api":
            log_activity(
                "Transcription Skipped",
                f"API transcription failed for: {video['title']}",
                "warning",
            )

    if result is None and mode in ("auto", "local"):
        result = _transcribe_locally(file_path)

    if result is None or not result.get("text", "").strip():
        return None

    _save_transcript(video_id, result)
    log_activity(
        "Transcript Ready",
        f"{video['title']} — {len(result['segments'])} segments "
        f"via {result['engine']}"
        + (f" ({result['language']})" if result.get("language") else ""),
        "success",
    )
    return result


def _save_transcript(video_id, result):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO transcripts
           (video_id, language, text, segments, engine)
           VALUES (?, ?, ?, ?, ?)""",
        (
            video_id,
            result.get("language", ""),
            result.get("text", ""),
            json.dumps(result.get("segments", [])),
            result.get("engine", ""),
        ),
    )
    conn.commit()
    conn.close()


# ─── API transcription ────────────────────────────────────────────────────

def _transcribe_via_api(video_path):
    """Upload audio to an OpenAI-compatible transcription endpoint."""
    cfg = get_ai_config()
    if not cfg:
        return None
    # Anthropic has no audio API — only OpenAI-compatible providers qualify.
    if cfg["provider"] != "openai":
        return None

    model = _whisper_api_model()
    audio_path, cleanup = _prepare_audio(video_path)
    if not audio_path:
        return None

    try:
        with open(audio_path, "rb") as fh:
            resp = requests.post(
                f"{cfg['base_url']}/audio/transcriptions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                files={"file": (os.path.basename(audio_path), fh)},
                data={
                    "model": model,
                    "response_format": "verbose_json",
                },
                timeout=AI_TRANSCRIBE_TIMEOUT,
            )
        if resp.status_code != 200:
            log_activity(
                "Transcription API Error",
                f"HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                "error",
            )
            return None
        data = resp.json()
    except (requests.RequestException, ValueError, OSError) as e:
        log_activity("Transcription API Error", str(e)[:200], "error")
        return None
    finally:
        cleanup()

    segments = _normalize_segments(data.get("segments", []))
    text = (data.get("text") or "").strip()
    if not text and segments:
        text = " ".join(seg["text"].strip() for seg in segments).strip()
    if not text:
        return None
    return {
        "language": data.get("language", ""),
        "text": text,
        "segments": segments,
        "engine": f"api:{model}",
    }


def _whisper_api_model():
    """
    Resolve the model name for API transcription.

    Local Whisper size names (tiny/base/...) map to OpenAI's whisper-1;
    anything else (e.g. Groq's whisper-large-v3) is passed through as-is.
    """
    setting_model = str(get_setting("whisper_model", "base")).strip()
    if setting_model in WHISPER_LOCAL_SIZES:
        return "whisper-1"
    return setting_model or "whisper-1"


def _prepare_audio(video_path):
    """
    Return (audio_path, cleanup_fn) suitable for upload.

    Large videos are downmixed to compact 16 kHz mono m4a with ffmpeg so the
    upload stays under the API size limit. When ffmpeg is unavailable the
    original file is used as-is.
    """
    try:
        if os.path.getsize(video_path) <= _API_SIZE_LIMIT:
            return video_path, lambda: None

        tmp_dir = tempfile.mkdtemp(prefix="clipforge_stt_")
        audio_path = os.path.join(tmp_dir, "audio.m4a")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "aac", "-b:a", "48k",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and os.path.exists(audio_path) \
                and os.path.getsize(audio_path) > 0:
            return audio_path, lambda: _remove_quietly(audio_path) or _remove_quietly(tmp_dir)
    except (OSError, subprocess.SubprocessError):
        pass
    return video_path, lambda: None


def _remove_quietly(path):
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
    except OSError:
        pass


def _normalize_segments(raw):
    """Coerce whisper API segment dicts to {start, end, text} floats."""
    segments = []
    for seg in raw or []:
        try:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start))
            text = str(seg.get("text", "")).strip()
        except (TypeError, ValueError):
            continue
        if text and end > start:
            segments.append({"start": start, "end": end, "text": text})
    return segments


# ─── Local transcription ──────────────────────────────────────────────────

def local_whisper_available():
    """True when a local Whisper implementation is importable."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _transcribe_locally(video_path):
    """Run a local Whisper model (faster-whisper preferred over openai-whisper)."""
    model_name = str(get_setting("whisper_model", "base")).strip() or "base"

    try:
        import faster_whisper
        model = faster_whisper.WhisperModel(model_name, device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(
            video_path, beam_size=5, vad_filter=True
        )
        segments = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if text:
                segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        text = " ".join(s["text"] for s in segments).strip()
        if not text:
            return None
        return {
            "language": getattr(info, "language", "") or "",
            "text": text,
            "segments": segments,
            "engine": f"local:faster-whisper/{model_name}",
        }
    except ImportError:
        pass
    except Exception as e:  # model download failure, decode error, ...
        log_activity("Local Transcription Error", str(e)[:200], "error")
        return None

    try:
        import whisper
        model = whisper.load_model(model_name)
        result = model.transcribe(video_path)
        segments = _normalize_segments(result.get("segments", []))
        if not segments:
            return None
        return {
            "language": result.get("language", "") or "",
            "text": (result.get("text") or "").strip(),
            "segments": segments,
            "engine": f"local:openai-whisper/{model_name}",
        }
    except ImportError:
        log_activity(
            "Transcription Unavailable",
            "No local Whisper installed — pip install faster-whisper "
            "(or set whisper_mode=api)",
            "warning",
        )
        return None
    except Exception as e:
        log_activity("Local Transcription Error", str(e)[:200], "error")
        return None
