"""
AI Content — LLM-generated hooks, titles, captions and hashtags.

Used when clips are created (automatic metadata) and via the API
(POST /api/ai/generate/<clip_id>) to (re)generate metadata per platform.
Falls back to deterministic templates when the AI is unavailable.
"""
import json

from engine.ai_client import AIError, ai_enabled, chat_json
from models import get_db, get_setting, log_activity

# Platform-specific constraints (hard limits + practical hashtag counts).
PLATFORM_LIMITS = {
    "youtube":   {"title": 100, "caption": 4900, "hashtags": 10, "tag_char": "#"},
    "tiktok":    {"title": 90,  "caption": 2100, "hashtags": 8,  "tag_char": "#"},
    "instagram": {"title": 90,  "caption": 2100, "hashtags": 12, "tag_char": "#"},
}

_DEFAULT_HASHTAGS = ["shorts", "viral", "clips"]

_SYSTEM_PROMPT = (
    "You are a viral short-form content writer. You write scroll-stopping "
    "titles, hooks and captions for YouTube Shorts, TikTok and Instagram "
    "Reels. Your style: punchy, curiosity-driven, zero clickbait lies, "
    "no emojis unless asked, no hashtag spam."
)

_USER_PROMPT_TEMPLATE = """Source video title: {video_title}
Clip time range: {start:.0f}s - {end:.0f}s
Target platform: {platform}

Transcript of this exact clip:
{transcript}

Write optimized posting metadata for this clip on {platform}.

Rules:
- "title": optimized clip title, max {title_limit} chars, no hashtags inside.
- "hook": the opening line idea, max 12 words, must create curiosity in 1-3 seconds.
- "caption": platform caption for the post, max {caption_limit} chars, 1-2 short lines,
  optionally ending with a question to drive comments. No hashtags inside.
- "hashtags": exactly {hashtag_count} relevant lowercase hashtags (no # symbol, no spaces).

Return JSON: {{"title": "...", "hook": "...", "caption": "...", "hashtags": ["...", "..."]}}"""


def generate_clip_metadata(video_title, transcript_slice, start, end,
                           platform="youtube", clip_title_hint=""):
    """
    Generate {title, hook, caption, hashtags, viral_score?} for one clip.

    Uses the LLM when available; otherwise returns template-based metadata
    so posting never blocks on AI availability.
    """
    if ai_enabled() and transcript_slice.strip():
        try:
            answer = chat_json(
                _SYSTEM_PROMPT,
                _build_prompt(video_title, transcript_slice, start, end, platform),
                temperature=0.8,
                max_tokens=600,
            )
            return _sanitize_metadata(answer, platform, video_title,
                                      clip_title_hint)
        except AIError as e:
            log_activity("AI Metadata Failed", str(e)[:200], "warning")

    return fallback_metadata(video_title, platform, clip_title_hint)


def _build_prompt(video_title, transcript_slice, start, end, platform):
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["youtube"])
    return _USER_PROMPT_TEMPLATE.format(
        video_title=video_title,
        start=start,
        end=end,
        platform=platform,
        transcript=transcript_slice[:4000],
        title_limit=limits["title"],
        caption_limit=limits["caption"],
        hashtag_count=limits["hashtags"],
    )


def _sanitize_metadata(answer, platform, video_title, clip_title_hint):
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["youtube"])
    if not isinstance(answer, dict):
        return fallback_metadata(video_title, platform, clip_title_hint)

    title = _clean(answer.get("title"), limits["title"])
    hook = _clean(answer.get("hook"), 140)
    caption = _clean(answer.get("caption"), limits["caption"])

    hashtags = answer.get("hashtags")
    if isinstance(hashtags, str):
        hashtags = [t.strip() for t in hashtags.replace("#", ",").split(",") if t.strip()]
    if not isinstance(hashtags, list):
        hashtags = []
    hashtags = [
        _clean(h, 40).lower().replace(" ", "").lstrip("#")
        for h in hashtags if h
    ]
    hashtags = [h for h in hashtags if h][: limits["hashtags"]]
    if not hashtags:
        hashtags = list(_DEFAULT_HASHTAGS)

    # A missing title is fatal for YouTube — always keep a fallback.
    if not title:
        title = clip_title_hint or video_title

    return {
        "title": title,
        "hook": hook,
        "caption": caption,
        "hashtags": hashtags,
    }


def fallback_metadata(video_title, platform="youtube", clip_title_hint=""):
    """Deterministic metadata used when the AI is off or fails."""
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["youtube"])
    title = clip_title_hint or video_title
    if len(title) > limits["title"]:
        title = title[: limits["title"] - 1].rstrip() + "…"
    return {
        "title": title,
        "hook": "",
        "caption": "",
        "hashtags": list(_DEFAULT_HASHTAGS),
    }


# ─── Composition helpers ──────────────────────────────────────────────────

def build_platform_caption(metadata, platform="youtube"):
    """
    Compose the final post text (caption + hashtags) within platform limits.
    Metadata is a dict with at least caption/hashtags (generate_clip_metadata shape).
    """
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS["youtube"])
    caption = (metadata.get("caption") or "").strip()
    hashtags = [h.lstrip("#").strip() for h in (metadata.get("hashtags") or []) if h]

    tag_line = " ".join(f"#{h}" for h in hashtags[: limits["hashtags"]])
    if caption:
        text = f"{caption}\n\n{tag_line}".strip()
    else:
        text = tag_line

    if len(text) > limits["caption"]:
        # Trim caption first, keep the hashtags.
        keep = limits["caption"] - len(tag_line) - 2
        text = f"{caption[:max(0, keep)].rstrip()}\n\n{tag_line}"
        if len(text) > limits["caption"]:
            text = text[: limits["caption"]].rstrip()
    return text


def transcript_slice_for(transcript, start, end, pad=1.5):
    """Extract the transcript text covering [start - pad, end + pad]."""
    if not transcript or not transcript.get("segments"):
        return ""
    lo, hi = start - pad, end + pad
    parts = [
        seg["text"]
        for seg in transcript["segments"]
        if seg["end"] > lo and seg["start"] < hi
    ]
    return " ".join(parts).strip()


# ─── Persistence ──────────────────────────────────────────────────────────

def generate_and_save_clip_metadata(clip_id, platform="youtube"):
    """
    (Re)generate and persist metadata for an existing clip.

    Returns (success, metadata_or_message).
    """
    conn = get_db()
    clip = conn.execute(
        """SELECT cl.id, cl.title, cl.start_time, cl.end_time,
                  v.title AS video_title
           FROM clips cl JOIN videos v ON cl.video_id = v.id
           WHERE cl.id = ?""",
        (clip_id,),
    ).fetchone()

    if not clip:
        conn.close()
        return False, "Clip not found"

    # Prefer the stored transcript (from the AI selection pass) when present.
    transcript = None
    row = conn.execute(
        "SELECT segments FROM transcripts WHERE video_id = "
        "(SELECT video_id FROM clips WHERE id = ?)",
        (clip_id,),
    ).fetchone()
    if row:
        try:
            segments = json.loads(row["segments"] or "[]")
        except ValueError:
            segments = []
        if segments:
            transcript = {"segments": segments}

    conn.close()

    slice_text = transcript_slice_for(
        transcript, clip["start_time"], clip["end_time"]
    ) if transcript else ""

    metadata = generate_clip_metadata(
        clip["video_title"],
        slice_text,
        clip["start_time"],
        clip["end_time"],
        platform=platform,
        clip_title_hint=clip["title"],
    )

    caption = build_platform_caption(metadata, platform)

    conn = get_db()
    conn.execute(
        """UPDATE clips SET title = ?, hook = ?, caption = ?, hashtags = ?,
           viral_score = CASE WHEN viral_score > 0 THEN viral_score ELSE 0 END
           WHERE id = ?""",
        (
            metadata["title"],
            metadata.get("hook", ""),
            caption,
            ",".join(metadata["hashtags"]),
            clip_id,
        ),
    )
    conn.commit()
    conn.close()

    log_activity(
        "AI Metadata Generated",
        f"Clip #{clip_id} ({platform}): {metadata['title'][:60]}",
        "success",
    )
    return True, {
        "clip_id": clip_id,
        "platform": platform,
        "title": metadata["title"],
        "hook": metadata.get("hook", ""),
        "caption": caption,
        "hashtags": metadata["hashtags"],
        "ai_generated": ai_enabled() and bool(slice_text.strip()),
    }


def auto_metadata_enabled():
    """Whether AI metadata should be generated during clip creation."""
    if not ai_enabled():
        return False
    return str(get_setting("ai_auto_metadata", "true")).lower() in (
        "1", "true", "yes", "on",
    )


def _clean(value, max_len):
    text = str(value or "").strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return text
