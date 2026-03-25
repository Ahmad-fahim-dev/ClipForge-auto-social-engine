"""
Video Downloader — downloads YouTube videos using yt-dlp.
"""
import os
import subprocess
import json
from models import get_db, log_activity
from config import DOWNLOADS_DIR, DOWNLOAD_FORMAT


def download_video(video_id):
    """Download a single video by DB id."""
    conn = get_db()
    video = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not video:
        conn.close()
        return False, "Video not found"

    if video["downloaded"]:
        conn.close()
        return True, "Already downloaded"

    url = video["url"]
    output_path = os.path.join(DOWNLOADS_DIR, f"{video['youtube_video_id']}.mp4")

    try:
        cmd = [
            "yt-dlp",
            "-f", DOWNLOAD_FORMAT,
            "--merge-output-format", "mp4",
            "-o", output_path,
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            url
        ]

        log_activity("Download Started", f"Downloading: {video['title']}", "info")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown download error"
            log_activity("Download Failed", f"{video['title']}: {error_msg}", "error")
            conn.close()
            return False, error_msg

        # Get video duration
        duration = get_video_duration(output_path)

        conn.execute(
            "UPDATE videos SET downloaded = 1, file_path = ?, duration = ? WHERE id = ?",
            (output_path, duration, video_id)
        )
        conn.commit()
        conn.close()

        log_activity("Download Complete", f"{video['title']} ({duration}s)", "success")
        return True, output_path

    except subprocess.TimeoutExpired:
        log_activity("Download Timeout", f"{video['title']}", "error")
        conn.close()
        return False, "Download timed out after 10 minutes"
    except Exception as e:
        log_activity("Download Error", f"{video['title']}: {str(e)}", "error")
        conn.close()
        return False, str(e)


def get_video_duration(file_path):
    """Get video duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return int(float(data.get("format", {}).get("duration", 0)))
    except Exception:
        pass
    return 0


def download_pending():
    """Download all pending videos."""
    conn = get_db()
    pending = conn.execute(
        "SELECT id, title FROM videos WHERE downloaded = 0"
    ).fetchall()
    conn.close()

    results = []
    for video in pending:
        success, msg = download_video(video["id"])
        results.append({
            "video_id": video["id"],
            "title": video["title"],
            "success": success,
            "message": msg
        })

    return results
