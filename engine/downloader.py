"""
Video Downloader — downloads YouTube videos using yt-dlp.
"""
import os
import time
import subprocess
import json
from models import get_db, log_activity
from engine.logger import logger
from config import DOWNLOADS_DIR, DOWNLOAD_FORMAT


def _retry(func, max_retries=2, delay=5):
    """Retry a function up to max_retries times with delay between attempts."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning("Attempt %d failed, retrying in %ds: %s", attempt + 1, delay, e)
                time.sleep(delay)
    logger.error("All %d retries exhausted: %s", max_retries, last_error)
    raise last_error


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
        logger.info("Starting download: %s", video['title'])

        def _run_download():
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "yt-dlp failed with unknown error")
            return result

        try:
            result = _retry(_run_download, max_retries=2, delay=5)
        except subprocess.TimeoutExpired:
            log_activity("Download Timeout", f"{video['title']}", "error")
            logger.error("Download timeout: %s", video['title'])
            conn.close()
            return False, "Download timed out after 10 minutes"
        except Exception as e:
            error_msg = str(e)
            log_activity("Download Failed", f"{video['title']}: {error_msg}", "error")
            logger.error("Download failed: %s - %s", video['title'], error_msg)
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
        logger.info("Download complete: %s (%ds)", video['title'], duration)
        return True, output_path

    except Exception as e:
        log_activity("Download Error", f"{video['title']}: {str(e)}", "error")
        logger.error("Download error: %s - %s", video['title'], e)
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
