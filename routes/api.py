"""
REST API routes for ClipForge dashboard.
"""
import os
import json
import traceback
from datetime import datetime
from flask import Blueprint, request, jsonify
from models import get_db, log_activity, get_setting, set_setting, get_stats
from engine.monitor import extract_channel_id, get_channel_info, check_all_channels
from engine.downloader import download_video, download_pending
from engine.clipper import process_video, process_pending
from engine.poster import post_clip, post_queued, test_account_connection
from engine.scheduler import get_scheduler_status, update_scheduler

api = Blueprint("api", __name__, url_prefix="/api")


# ─── Stats ───────────────────────────────────────────────────────────────

@api.route("/stats")
def stats():
    return jsonify(get_stats())


# ─── Activity Log ────────────────────────────────────────────────────────

@api.route("/activity")
def activity():
    limit = request.args.get("limit", 50, type=int)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─── Channels ────────────────────────────────────────────────────────────

@api.route("/channels", methods=["GET"])
def list_channels():
    conn = get_db()
    channels = conn.execute(
        "SELECT * FROM channels ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(c) for c in channels])


@api.route("/channels", methods=["POST"])
def add_channel():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    channel_id = extract_channel_id(url)
    if not channel_id:
        return jsonify({"error": "Could not extract channel ID from URL. Use format: youtube.com/channel/UC..."}), 400

    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM channels WHERE channel_id = ?", (channel_id,)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Channel already added"}), 400

    info = get_channel_info(channel_id)
    name = data.get("name") or (info["name"] if info else "Unknown Channel")

    conn.execute(
        "INSERT INTO channels (name, youtube_url, channel_id, thumbnail_url) VALUES (?, ?, ?, ?)",
        (name, url, channel_id, info.get("thumbnail_url", "") if info else "")
    )
    conn.commit()
    conn.close()

    log_activity("Channel Added", f"{name} ({channel_id})", "success")
    return jsonify({"success": True, "name": name, "channel_id": channel_id})


@api.route("/channels/<int:channel_id>", methods=["DELETE"])
def delete_channel(channel_id):
    conn = get_db()
    ch = conn.execute("SELECT name FROM channels WHERE id = ?", (channel_id,)).fetchone()
    conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()
    if ch:
        log_activity("Channel Removed", ch["name"], "info")
    return jsonify({"success": True})


@api.route("/channels/<int:channel_id>/toggle", methods=["POST"])
def toggle_channel(channel_id):
    conn = get_db()
    conn.execute(
        "UPDATE channels SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (channel_id,)
    )
    conn.commit()
    ch = conn.execute("SELECT name, active FROM channels WHERE id = ?", (channel_id,)).fetchone()
    conn.close()
    return jsonify({"success": True, "active": ch["active"] if ch else 0})


# ─── Videos ──────────────────────────────────────────────────────────────

@api.route("/videos")
def list_videos():
    conn = get_db()
    videos = conn.execute(
        """SELECT v.*, c.name as channel_name,
           CASE WHEN v.downloaded = 0 THEN 'new'
                WHEN v.processed = 0 THEN 'downloaded'
                ELSE 'clipped' END as status
           FROM videos v JOIN channels c ON v.channel_id = c.id
           ORDER BY v.created_at DESC LIMIT 100"""
    ).fetchall()
    conn.close()
    return jsonify([dict(v) for v in videos])


@api.route("/videos/<int:video_id>/download", methods=["POST"])
def action_download_single(video_id):
    try:
        success, msg = download_video(video_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/videos/<int:video_id>/clip", methods=["POST"])
def action_clip_single(video_id):
    try:
        success, msg = process_video(video_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ─── Clips ───────────────────────────────────────────────────────────────

@api.route("/clips")
def list_clips():
    conn = get_db()
    clips = conn.execute(
        """SELECT cl.*, v.title as video_title, ch.name as channel_name
           FROM clips cl
           JOIN videos v ON cl.video_id = v.id
           JOIN channels ch ON v.channel_id = ch.id
           ORDER BY cl.created_at DESC LIMIT 100"""
    ).fetchall()
    conn.close()
    result = []
    for c in clips:
        d = dict(c)
        # Provide filename for media URL
        if d.get("file_path"):
            d["filename"] = os.path.basename(d["file_path"])
        if d.get("thumbnail_path"):
            d["thumbnail"] = os.path.basename(d["thumbnail_path"])
        result.append(d)
    return jsonify(result)


@api.route("/clips/<int:clip_id>", methods=["DELETE"])
def delete_clip(clip_id):
    conn = get_db()
    clip = conn.execute("SELECT file_path, thumbnail_path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if clip:
        for path in [clip["file_path"], clip["thumbnail_path"]]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
    conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ─── Posts ───────────────────────────────────────────────────────────────

@api.route("/posts")
def list_posts():
    conn = get_db()
    posts = conn.execute(
        """SELECT p.*, cl.title as clip_title, cl.thumbnail_path
           FROM posts p JOIN clips cl ON p.clip_id = cl.id
           ORDER BY p.created_at DESC LIMIT 100"""
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in posts])


@api.route("/posts", methods=["POST"])
def create_post():
    data = request.json
    clip_id = data.get("clip_id")
    platform = data.get("platform", "")
    caption = data.get("caption", "")

    if not clip_id or not platform:
        return jsonify({"error": "clip_id and platform are required"}), 400

    # Validate platform
    if platform not in ("youtube", "tiktok", "instagram"):
        return jsonify({"error": f"Invalid platform: {platform}"}), 400

    # Check account connected
    conn = get_db()
    account = conn.execute(
        "SELECT connected FROM accounts WHERE platform = ?", (platform,)
    ).fetchone()
    if not account or not account["connected"]:
        conn.close()
        return jsonify({"error": f"{platform.title()} account not connected. Go to Accounts page to connect it."}), 400

    clip = conn.execute("SELECT id, title FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not clip:
        conn.close()
        return jsonify({"error": "Clip not found"}), 404

    final_caption = caption or f"{clip['title']} #shorts #viral"
    conn.execute(
        "INSERT INTO posts (clip_id, platform, caption, status) VALUES (?, ?, ?, 'queued')",
        (clip_id, platform, final_caption)
    )
    conn.commit()
    conn.close()

    log_activity("Post Queued", f"{clip['title']} → {platform}", "info")
    return jsonify({"success": True, "platform": platform})


@api.route("/posts/<int:post_id>/retry", methods=["POST"])
def retry_post(post_id):
    conn = get_db()
    conn.execute("UPDATE posts SET status = 'queued', error_message = '' WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@api.route("/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id):
    conn = get_db()
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ─── Accounts — STRONG CONNECTION LOGIC ──────────────────────────────────

@api.route("/accounts")
def list_accounts():
    conn = get_db()
    accounts = conn.execute(
        "SELECT id, platform, username, connected, channel_url, last_used, api_key FROM accounts"
    ).fetchall()
    conn.close()
    result = []
    for a in accounts:
        d = dict(a)
        # Mask API key for security
        if d.get("api_key") and len(d["api_key"]) > 4:
            d["api_key_preview"] = "***" + d["api_key"][-4:]
        else:
            d["api_key_preview"] = ""
        d.pop("api_key", None)
        result.append(d)
    return jsonify(result)


@api.route("/accounts/<platform>/connect", methods=["POST"])
def connect_account(platform):
    """
    Connect a social media account with proper validation per platform.

    YouTube:  requires api_key + channel_url
    TikTok:   requires username + password (for Selenium login)
    Instagram: requires username + password (for Selenium login)
    """
    if platform not in ("youtube", "tiktok", "instagram"):
        return jsonify({"error": f"Invalid platform: {platform}"}), 400

    data = request.json or {}
    errors = []

    if platform == "youtube":
        api_key = data.get("api_key", "").strip()
        channel_url = data.get("channel_url", "").strip()
        if not api_key:
            errors.append("API Key is required")
        if api_key and len(api_key) < 10:
            errors.append("API Key looks too short. Get a valid key from Google Cloud Console.")
        if errors:
            return jsonify({"error": " | ".join(errors)}), 400

        # Test YouTube API key
        test_ok, test_msg = test_account_connection("youtube", {
            "api_key": api_key,
            "channel_url": channel_url
        })

        conn = get_db()
        conn.execute(
            """UPDATE accounts SET username = ?, connected = ?, channel_url = ?,
               api_key = ?, last_used = ? WHERE platform = 'youtube'""",
            (
                data.get("username", channel_url),
                1 if test_ok else 0,
                channel_url,
                api_key,
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()

        if test_ok:
            log_activity("Account Connected", f"YouTube: API key verified", "success")
            return jsonify({"success": True, "message": test_msg, "connected": True})
        else:
            log_activity("Account Failed", f"YouTube: {test_msg}", "error")
            return jsonify({"success": False, "message": test_msg, "connected": False}), 400

    elif platform == "tiktok":
        username = data.get("username", "").strip()
        session_id = data.get("session_id", "").strip()
        if not username:
            errors.append("Username is required")
        if errors:
            return jsonify({"error": " | ".join(errors)}), 400

        # Store credentials
        session_data = {"session_id": session_id} if session_id else {}

        conn = get_db()
        conn.execute(
            """UPDATE accounts SET username = ?, connected = 1,
               session_data = ?, last_used = ? WHERE platform = 'tiktok'""",
            (
                username,
                json.dumps(session_data),
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()

        log_activity("Account Connected", f"TikTok: @{username}", "success")
        return jsonify({"success": True, "message": f"TikTok @{username} connected. First upload may require manual login.", "connected": True})

    elif platform == "instagram":
        username = data.get("username", "").strip()
        session_id = data.get("session_id", "").strip()
        if not username:
            errors.append("Username is required")
        if errors:
            return jsonify({"error": " | ".join(errors)}), 400

        session_data = {"session_id": session_id} if session_id else {}

        conn = get_db()
        conn.execute(
            """UPDATE accounts SET username = ?, connected = 1,
               session_data = ?, last_used = ? WHERE platform = 'instagram'""",
            (
                username,
                json.dumps(session_data),
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()

        log_activity("Account Connected", f"Instagram: @{username}", "success")
        return jsonify({"success": True, "message": f"Instagram @{username} connected. First upload may require manual login.", "connected": True})


@api.route("/accounts/<platform>/disconnect", methods=["POST"])
def disconnect_account(platform):
    if platform not in ("youtube", "tiktok", "instagram"):
        return jsonify({"error": "Invalid platform"}), 400

    conn = get_db()
    conn.execute(
        """UPDATE accounts SET connected = 0, username = '', api_key = '',
           session_data = '{}', channel_url = '' WHERE platform = ?""",
        (platform,)
    )
    conn.commit()
    conn.close()
    log_activity("Account Disconnected", platform.title(), "info")
    return jsonify({"success": True})


@api.route("/accounts/<platform>/test", methods=["POST"])
def test_account(platform):
    """Test if a connected account can reach the platform API."""
    if platform not in ("youtube", "tiktok", "instagram"):
        return jsonify({"error": "Invalid platform"}), 400

    conn = get_db()
    account = conn.execute(
        "SELECT * FROM accounts WHERE platform = ?", (platform,)
    ).fetchone()
    conn.close()

    if not account or not account["connected"]:
        return jsonify({"success": False, "message": f"{platform.title()} is not connected."}), 400

    creds = {
        "api_key": account["api_key"],
        "username": account["username"],
        "channel_url": account["channel_url"],
        "session_data": json.loads(account["session_data"] or "{}"),
    }

    test_ok, test_msg = test_account_connection(platform, creds)
    return jsonify({"success": test_ok, "message": test_msg})


# ─── Settings ────────────────────────────────────────────────────────────

@api.route("/settings")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    result = {}
    for r in rows:
        v = r["value"]
        # Convert types
        if v.lower() in ("true", "false"):
            result[r["key"]] = v.lower() == "true"
        elif v.isdigit():
            result[r["key"]] = int(v)
        else:
            result[r["key"]] = v
    return jsonify(result)


@api.route("/settings", methods=["POST"])
def update_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, value)
    update_scheduler()
    log_activity("Settings Updated", ", ".join(f"{k}={v}" for k, v in data.items()), "info")
    return jsonify({"success": True})


# ─── Manual Actions ──────────────────────────────────────────────────────

@api.route("/actions/check-channels", methods=["POST"])
def action_check_channels():
    try:
        new_count = check_all_channels()
        return jsonify({"success": True, "new_videos": new_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api.route("/actions/download/<int:video_id>", methods=["POST"])
def action_download(video_id):
    try:
        success, msg = download_video(video_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/actions/download-all", methods=["POST"])
def action_download_all():
    try:
        results = download_pending()
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/actions/process/<int:video_id>", methods=["POST"])
def action_process(video_id):
    try:
        success, msg = process_video(video_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/actions/process-all", methods=["POST"])
def action_process_all():
    try:
        results = process_pending()
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/actions/post/<int:post_id>", methods=["POST"])
def action_post(post_id):
    try:
        success, msg = post_clip(post_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/actions/post-all", methods=["POST"])
def action_post_all():
    try:
        results = post_queued()
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/scheduler/status")
def scheduler_status():
    return jsonify(get_scheduler_status())
