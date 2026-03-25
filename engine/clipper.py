"""
Clip Engine — extracts viral short-form clips from downloaded videos.
Uses scene detection + FFmpeg for smart cuts and vertical crops.
"""
import os
import subprocess
import json
import random
from models import get_db, log_activity, get_setting
from config import CLIPS_DIR, THUMBNAILS_DIR


def detect_scenes(video_path, threshold=27.0):
    """Detect scene changes in a video using ffprobe scene detection."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_frames",
            "-read_intervals", "%+300",  # analyze first 5 min
            "-f", "lavfi",
            f"movie='{video_path.replace(os.sep, '/')}',select='gt(scene\\,0.3)'",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            frames = data.get("frames", [])
            timestamps = []
            for frame in frames:
                ts = float(frame.get("best_effort_timestamp_time",
                           frame.get("pts_time", 0)))
                timestamps.append(ts)
            return sorted(timestamps)
    except Exception:
        pass
    return []


def get_video_info(video_path):
    """Get video width, height, and duration."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    return {
                        "width": int(stream.get("width", 1920)),
                        "height": int(stream.get("height", 1080)),
                        "duration": duration
                    }
            return {"width": 1920, "height": 1080, "duration": duration}
    except Exception:
        pass
    return {"width": 1920, "height": 1080, "duration": 0}


def generate_clip_segments(duration, scene_timestamps, min_dur=25, max_dur=59, count=5):
    """Generate clip segments from scene timestamps or evenly spaced."""
    segments = []

    if scene_timestamps and len(scene_timestamps) >= 2:
        # Use scene changes to find good cut points
        for i in range(len(scene_timestamps) - 1):
            start = scene_timestamps[i]
            # Find best end point
            for j in range(i + 1, len(scene_timestamps)):
                clip_dur = scene_timestamps[j] - start
                if min_dur <= clip_dur <= max_dur:
                    segments.append((start, scene_timestamps[j]))
                    break
                elif clip_dur > max_dur:
                    segments.append((start, start + max_dur))
                    break

            if len(segments) >= count * 2:
                break

    # If not enough scenes, create evenly-spaced segments
    if len(segments) < count and duration > min_dur * 2:
        skip_start = min(60, duration * 0.05)  # Skip intro
        skip_end = min(60, duration * 0.05)     # Skip outro
        usable = duration - skip_start - skip_end

        if usable > min_dur:
            clip_dur = min(max_dur, max(min_dur, usable / count))
            step = usable / max(count, 1)

            for i in range(count):
                start = skip_start + (i * step)
                end = min(start + clip_dur, duration - skip_end)
                if end - start >= min_dur:
                    segments.append((start, end))

    # Deduplicate + pick top N
    unique = []
    for seg in segments:
        overlap = False
        for u in unique:
            if abs(seg[0] - u[0]) < 10:
                overlap = True
                break
        if not overlap:
            unique.append(seg)

    random.shuffle(unique)
    return unique[:count]


def extract_clip(video_path, start, end, output_path, video_info):
    """Extract a single clip with vertical crop (9:16)."""
    src_w = video_info["width"]
    src_h = video_info["height"]

    # Calculate center crop for 9:16
    target_ratio = 9 / 16
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider, crop sides
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
        crop_x = (src_w - crop_w) // 2
        crop_y = 0
    else:
        # Source is taller, crop top/bottom
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
        crop_x = 0
        crop_y = (src_h - crop_h) // 2

    filter_str = (
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale=1080:1920:flags=lanczos"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.returncode == 0


def generate_thumbnail(clip_path, thumbnail_path):
    """Generate thumbnail from clip midpoint."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-vf", "select='eq(n,30)',scale=360:640",
            "-frames:v", "1",
            thumbnail_path
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass


def process_video(video_id):
    """Process a downloaded video — generate clips from it."""
    conn = get_db()
    video = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not video or not video["downloaded"] or not video["file_path"]:
        conn.close()
        return False, "Video not ready for processing"

    if video["processed"]:
        conn.close()
        return True, "Already processed"

    file_path = video["file_path"]
    if not os.path.exists(file_path):
        conn.close()
        return False, f"Video file not found: {file_path}"

    clips_per_video = int(get_setting("clips_per_video", 5))
    min_dur = int(get_setting("clip_min_duration", 25))
    max_dur = int(get_setting("clip_max_duration", 59))

    log_activity("Processing Started", f"Generating clips for: {video['title']}", "info")

    video_info = get_video_info(file_path)
    if video_info["duration"] < min_dur:
        conn.execute("UPDATE videos SET processed = 1 WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        return False, "Video too short for clips"

    scene_ts = detect_scenes(file_path)
    segments = generate_clip_segments(
        video_info["duration"], scene_ts,
        min_dur, max_dur, clips_per_video
    )

    created_clips = 0
    for i, (start, end) in enumerate(segments):
        clip_filename = f"{video['youtube_video_id']}_clip{i+1}.mp4"
        clip_path = os.path.join(CLIPS_DIR, clip_filename)
        thumb_filename = f"{video['youtube_video_id']}_clip{i+1}.jpg"
        thumb_path = os.path.join(THUMBNAILS_DIR, thumb_filename)

        clip_title = f"{video['title']} - Part {i+1}"
        if len(clip_title) > 100:
            clip_title = clip_title[:97] + "..."

        success = extract_clip(file_path, start, end, clip_path, video_info)
        if success and os.path.exists(clip_path):
            generate_thumbnail(clip_path, thumb_path)

            conn.execute(
                """INSERT INTO clips (video_id, title, file_path, thumbnail_path,
                   duration, start_time, end_time, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'ready')""",
                (video_id, clip_title, clip_path,
                 thumb_path if os.path.exists(thumb_path) else "",
                 round(end - start, 1), start, end)
            )
            created_clips += 1

    conn.execute("UPDATE videos SET processed = 1 WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()

    log_activity(
        "Processing Complete",
        f"{created_clips} clips from: {video['title']}",
        "success"
    )
    return True, f"Created {created_clips} clips"


def process_pending():
    """Process all downloaded but unprocessed videos."""
    conn = get_db()
    pending = conn.execute(
        "SELECT id, title FROM videos WHERE downloaded = 1 AND processed = 0"
    ).fetchall()
    conn.close()

    results = []
    for video in pending:
        success, msg = process_video(video["id"])
        results.append({
            "video_id": video["id"],
            "title": video["title"],
            "success": success,
            "message": msg
        })
    return results
