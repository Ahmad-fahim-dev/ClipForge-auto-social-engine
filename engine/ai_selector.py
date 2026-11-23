"""
AI Selector — LLM-powered viral moment selection.

Given a Whisper transcript the model ranks the most engaging,
self-contained segments for short-form content. Every candidate is
validated and snapped to natural speech boundaries before use.
Falls back to the heuristic (scene-based) selector on any failure.
"""
from engine.ai_client import AIError, ai_enabled, chat_json
from models import log_activity

# Prompt budget for the transcript excerpt (characters).
_TRANSCRIPT_CHAR_BUDGET = 14000
# Snap tolerance when aligning LLM timestamps to speech boundaries (seconds).
_SNAP_TOLERANCE = 8.0

_SYSTEM_PROMPT = (
    "You are a world-class short-form content strategist who has produced "
    "hundreds of viral YouTube Shorts, TikToks and Reels. You excel at "
    "reading a transcript and identifying the moments with the highest "
    "retention potential: strong hooks, emotional peaks, surprising facts, "
    "story payoffs, contrarian takes, and quotable one-liners."
)

_USER_PROMPT_TEMPLATE = """Video title: {title}
Total video duration: {duration:.0f} seconds

Below is the timestamped transcript, grouped into numbered time blocks.

{transcript}

Select the {count} best segments for short-form clips (YouTube Shorts / TikTok / Reels).

Rules for each segment:
- Duration must be between {min_dur} and {max_dur} seconds.
- Start and end at natural speech boundaries (use the block timestamps as reference).
- The clip must be self-contained: a viewer with zero context must understand and enjoy it.
- Prefer moments with a strong hook in the first 1-3 seconds.
- Do NOT overlap segments with each other.
- Ignore intros, outros, sponsor reads, and calls to subscribe.

Return JSON of this exact shape:
{{
  "segments": [
    {{
      "start": <seconds, number>,
      "end": <seconds, number>,
      "hook": "<one punchy sentence (max 12 words) describing why this moment stops the scroll>",
      "viral_score": <1-10, how likely this is to go viral>,
      "reason": "<one short sentence explaining the pick>"
    }}
  ]
}}"""


def select_viral_segments(transcript, video_title, duration, count,
                          min_dur=25, max_dur=59):
    """
    Ask the LLM to pick the most viral segments from a transcript.

    Returns a list of dicts sorted by score:
        [{start, end, hook, viral_score, reason}]
    or None when AI is unavailable / the answer is unusable (caller then
    falls back to the heuristic selector).
    """
    if not ai_enabled() or not transcript or not transcript.get("segments"):
        return None

    blocks = _compact_blocks(transcript["segments"], _TRANSCRIPT_CHAR_BUDGET)
    if not blocks:
        return None

    prompt = _USER_PROMPT_TEMPLATE.format(
        title=video_title,
        duration=duration,
        transcript=_format_blocks(blocks),
        count=count,
        min_dur=int(min_dur),
        max_dur=int(max_dur),
    )

    try:
        answer = chat_json(
            _SYSTEM_PROMPT,
            prompt,
            temperature=0.3,
            max_tokens=1800,
        )
    except AIError as e:
        log_activity("AI Selection Failed", str(e)[:200], "warning")
        return None

    candidates = answer.get("segments") if isinstance(answer, dict) else answer
    if not isinstance(candidates, list):
        return None

    segments = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start"))
            end = float(raw.get("end"))
        except (TypeError, ValueError):
            continue

        seg = _validate_segment(
            start, end, duration, min_dur, max_dur,
            transcript["segments"],
        )
        if seg is None:
            continue
        seg["hook"] = _clean_text(raw.get("hook"), 140)
        seg["reason"] = _clean_text(raw.get("reason"), 200)
        try:
            seg["viral_score"] = max(0.0, min(10.0, float(raw.get("viral_score", 5))))
        except (TypeError, ValueError):
            seg["viral_score"] = 5.0
        segments.append(seg)

    segments = _dedupe_overlaps(segments)
    segments.sort(key=lambda s: s["viral_score"], reverse=True)

    picked = segments[:count]
    if not picked:
        return None

    picked.sort(key=lambda s: s["start"])
    score_str = ", ".join(f"{s['viral_score']:.0f}" for s in picked)
    log_activity(
        "AI Clip Selection",
        f"{len(picked)} segments picked from '{video_title}' (scores: {score_str})",
        "info",
    )
    return picked


# ─── Validation helpers ───────────────────────────────────────────────────

def _validate_segment(start, end, duration, min_dur, max_dur, speech_segments):
    """
    Clamp a candidate to the video, enforce duration limits, and snap the
    cut points to nearby speech boundaries (natural pauses = clean cuts).
    Returns {start, end} or None when the candidate is unusable.
    """
    # Hard bounds
    if start < 0:
        start = 0.0
    if end > duration:
        end = float(duration)
    if end <= start:
        return None

    # Enforce duration window
    if end - start > max_dur:
        end = start + max_dur
    if end - start < min_dur:
        end = start + min_dur
    if end > duration:
        # Try shifting the window left instead of dropping the tail
        start = max(0.0, end - min_dur)
    if end - start < min_dur or end > duration + 0.5:
        return None

    # Snap to speech boundaries for clean cuts
    start = _snap(start, speech_segments, "start", duration)
    end = _snap(end, speech_segments, "end", duration)

    if end - start < min_dur * 0.8:
        return None
    return {"start": round(start, 2), "end": round(end, 2)}


def _snap(timestamp, speech_segments, edge, duration):
    """
    Move a cut point to the nearest speech boundary within tolerance.
    'start' snaps to a segment start; 'end' snaps to a segment end.
    """
    if not speech_segments:
        return timestamp

    if edge == "start":
        targets = [s["start"] for s in speech_segments] + [0.0]
    else:
        targets = [s["end"] for s in speech_segments] + [duration]

    best = min(targets, key=lambda t: abs(t - timestamp))
    if abs(best - timestamp) <= _SNAP_TOLERANCE:
        return best
    return timestamp


def _dedupe_overlaps(segments, min_gap=5.0):
    """Drop candidates that overlap an already-kept, higher-scored segment."""
    ordered = sorted(segments, key=lambda s: s["viral_score"], reverse=True)
    kept = []
    for seg in ordered:
        if any(
            seg["start"] < k["end"] + min_gap and seg["end"] > k["start"] - min_gap
            for k in kept
        ):
            continue
        kept.append(seg)
    return kept


# ─── Transcript compaction ────────────────────────────────────────────────

def _compact_blocks(segments, char_budget):
    """
    Merge whisper segments into time blocks that fit the prompt budget.
    Block granularity grows automatically for long videos so the full
    timeline is always covered.
    """
    if not segments:
        return []

    for target in (30, 60, 120, 240, 300):
        blocks = _merge_into_blocks(segments, target)
        if len(_format_blocks(blocks)) <= char_budget:
            return blocks

    # Even at 5-minute blocks it does not fit — hard-truncate block text.
    return _truncate_blocks(_merge_into_blocks(segments, 300), char_budget)


def _merge_into_blocks(segments, block_seconds):
    blocks = []
    current = None
    for seg in segments:
        if current is None or seg["start"] >= current["end"]:
            if current:
                blocks.append(current)
            current = {
                "start": seg["start"],
                "end": seg["start"] + block_seconds,
                "text": seg["text"],
            }
        else:
            current["text"] = (current["text"] + " " + seg["text"]).strip()
    if current:
        blocks.append(current)
    return blocks


def _format_blocks(blocks):
    return "\n".join(
        f"#{i + 1} [{_ts(b['start'])} - {_ts(b['end'])}] {b['text']}"
        for i, b in enumerate(blocks)
    )


def _truncate_blocks(blocks, char_budget):
    total = sum(len(b["text"]) for b in blocks)
    if total <= char_budget:
        return blocks
    per_block = max(120, char_budget // len(blocks))
    for b in blocks:
        if len(b["text"]) > per_block:
            b["text"] = b["text"][: per_block - 3].rsplit(" ", 1)[0] + "..."
    return blocks


def _ts(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _clean_text(value, max_len):
    text = str(value or "").strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return text
