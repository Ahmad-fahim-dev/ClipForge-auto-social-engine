"""
Auto Poster — posts clips to TikTok, Instagram, YouTube Shorts.
Uses Selenium for TikTok/Instagram, YouTube Data API for YouTube.
"""
import os
import time
import json
import requests
from datetime import datetime
from models import get_db, log_activity


def test_account_connection(platform, creds):
    """
    Test connectivity/credentials for a platform account.

    Returns (success: bool, message: str).

    youtube:   validates the API key with a live YouTube Data API v3 call.
    tiktok:    validates username and session cookie presence.
    instagram: validates username and session cookie presence.
    """
    if platform == "youtube":
        api_key = (creds.get("api_key") or "").strip()
        if not api_key:
            return False, "YouTube API key is missing."

        try:
            # videoCategories is a cheap call any valid YouTube Data API key can make
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videoCategories",
                params={"part": "snippet", "regionCode": "US", "key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "YouTube API key verified successfully."
            try:
                err = resp.json().get("error", {}).get("message", "")
            except Exception:
                err = ""
            if not err:
                err = (resp.text or "")[:200]
            return False, f"YouTube API key check failed (HTTP {resp.status_code}): {err}"
        except Exception as e:
            return False, f"YouTube API key check failed: {str(e)}"

    if platform in ("tiktok", "instagram"):
        username = (creds.get("username") or "").strip()
        session_data = creds.get("session_data") or {}
        if not username:
            return False, f"{platform.title()} username is missing."
        if session_data.get("session_id"):
            return True, (
                f"{platform.title()} @{username} credentials saved. "
                "Session will be verified on the first upload."
            )
        return True, (
            f"{platform.title()} @{username} saved. No session ID provided — "
            "you will need to log in manually on the first upload."
        )

    return False, f"Unknown platform: {platform}"


def post_to_youtube(clip_path, title, description="", tags=None):
    """
    Post a clip to YouTube Shorts using YouTube Data API v3.
    Requires OAuth2 credentials in accounts table.
    """
    conn = get_db()
    account = conn.execute(
        "SELECT * FROM accounts WHERE platform = 'youtube'"
    ).fetchone()
    conn.close()

    if not account or not account["connected"]:
        return False, "YouTube account not connected. Please connect via Settings."

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials

        session_data = json.loads(account["session_data"] or "{}")
        if not session_data.get("token"):
            return False, "YouTube OAuth token missing. Re-connect your account."

        creds = Credentials(
            token=session_data.get("token"),
            refresh_token=session_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=session_data.get("client_id", ""),
            client_secret=session_data.get("client_secret", ""),
        )

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description or f"{title} #shorts #viral",
                "tags": tags or ["shorts", "viral", "clips"],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(clip_path, mimetype="video/mp4", resumable=True)

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = request.execute()
        video_id = response.get("id", "")
        post_url = f"https://youtube.com/shorts/{video_id}" if video_id else ""

        return True, post_url

    except Exception as e:
        return False, f"YouTube upload error: {str(e)}"


def post_to_tiktok(clip_path, caption=""):
    """
    Post a clip to TikTok using Selenium browser automation.
    Requires logged-in session saved in accounts table.
    """
    conn = get_db()
    account = conn.execute(
        "SELECT * FROM accounts WHERE platform = 'tiktok'"
    ).fetchone()
    conn.close()

    if not account or not account["connected"]:
        return False, "TikTok account not connected. Please connect via Settings."

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
        from config import SESSIONS_DIR

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"--user-data-dir={os.path.join(SESSIONS_DIR, 'tiktok')}")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

        try:
            driver.get("https://www.tiktok.com/upload")
            time.sleep(5)

            # Upload file
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(os.path.abspath(clip_path))
            time.sleep(10)

            # Set caption
            if caption:
                try:
                    caption_box = WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-text='true']"))
                    )
                    caption_box.clear()
                    caption_box.send_keys(caption[:150])
                except Exception:
                    pass

            # Click post
            time.sleep(3)
            post_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-e2e='post-button'], .btn-post"))
            )
            post_btn.click()
            time.sleep(10)

            return True, "Posted to TikTok"

        finally:
            driver.quit()

    except Exception as e:
        return False, f"TikTok upload error: {str(e)}"


def post_to_instagram(clip_path, caption=""):
    """
    Post a clip to Instagram Reels using Selenium browser automation.
    Requires logged-in session saved in accounts table.
    """
    conn = get_db()
    account = conn.execute(
        "SELECT * FROM accounts WHERE platform = 'instagram'"
    ).fetchone()
    conn.close()

    if not account or not account["connected"]:
        return False, "Instagram account not connected. Please connect via Settings."

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
        from config import SESSIONS_DIR

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"--user-data-dir={os.path.join(SESSIONS_DIR, 'instagram')}")

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

        try:
            driver.get("https://www.instagram.com/")
            time.sleep(5)

            # Click new post
            new_post = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "svg[aria-label='New post']"))
            )
            new_post.click()
            time.sleep(3)

            # Upload file
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(os.path.abspath(clip_path))
            time.sleep(8)

            # Navigate through steps (Next -> Next -> Share)
            for _ in range(2):
                try:
                    next_btn = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[text()='Next']"))
                    )
                    next_btn.click()
                    time.sleep(3)
                except Exception:
                    pass

            # Add caption
            if caption:
                try:
                    caption_area = driver.find_element(
                        By.CSS_SELECTOR, "textarea[aria-label='Write a caption...']"
                    )
                    caption_area.send_keys(caption[:2200])
                    time.sleep(2)
                except Exception:
                    pass

            # Share
            share_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[text()='Share']"))
            )
            share_btn.click()
            time.sleep(10)

            return True, "Posted to Instagram"

        finally:
            driver.quit()

    except Exception as e:
        return False, f"Instagram upload error: {str(e)}"


PLATFORM_HANDLERS = {
    "youtube": post_to_youtube,
    "tiktok": post_to_tiktok,
    "instagram": post_to_instagram,
}


def _format_hashtags(raw):
    """Turn a comma-separated hashtag string into a '#tag #tag' line."""
    tags = [t.strip().lstrip("#") for t in (raw or "").split(",") if t.strip()]
    if not tags:
        return "#shorts #viral #clips"
    return " ".join(f"#{t}" for t in tags)


def post_clip(post_id):
    """Post a clip from the queue."""
    conn = get_db()
    post = conn.execute(
        """SELECT p.*, c.file_path, c.title as clip_title,
                  c.hook as clip_hook, c.caption as clip_caption,
                  c.hashtags as clip_hashtags
           FROM posts p JOIN clips c ON p.clip_id = c.id
           WHERE p.id = ?""",
        (post_id,)
    ).fetchone()

    if not post:
        conn.close()
        return False, "Post not found"

    platform = post["platform"]
    handler = PLATFORM_HANDLERS.get(platform)
    if not handler:
        conn.close()
        return False, f"Unknown platform: {platform}"

    clip_path = post["file_path"]

    # Caption priority: manual per-post caption → AI-generated clip caption →
    # AI hook + generic hashtags → classic fallback.
    caption = (post["caption"] or "").strip()
    if not caption:
        ai_caption = (post["clip_caption"] or "").strip()
        if ai_caption:
            caption = ai_caption
        elif (post["clip_hook"] or "").strip():
            hashtags = _format_hashtags(post["clip_hashtags"])
            caption = f"{post['clip_hook'].strip()}\n\n{hashtags}".strip()
        else:
            caption = f"{post['clip_title']} #shorts #viral #clips"

    # Title priority for YouTube: the clip title (AI-generated when the AI
    # pipeline produced it).
    clip_title = (post["clip_title"] or "").strip()

    if platform == "youtube":
        yt_tags = [t.strip().lstrip("#") for t in (post["clip_hashtags"] or "").split(",") if t.strip()]
        success, result = handler(clip_path, clip_title, caption, yt_tags or None)
    else:
        success, result = handler(clip_path, caption)

    if success:
        conn.execute(
            """UPDATE posts SET status = 'posted', posted_at = ?, post_url = ?
               WHERE id = ?""",
            (datetime.utcnow().isoformat(), result, post_id)
        )
    else:
        conn.execute(
            "UPDATE posts SET status = 'failed', error_message = ? WHERE id = ?",
            (result, post_id)
        )

    # Commit + close BEFORE logging: log_activity opens its own connection,
    # and writing while this transaction is open deadlocks SQLite
    # ("database is locked").
    conn.commit()
    conn.close()

    if success:
        log_activity("Post Success", f"{post['clip_title']} → {platform}", "success")
    else:
        log_activity("Post Failed", f"{post['clip_title']} → {platform}: {result}", "error")

    return success, result


def post_queued():
    """Post all queued items with delay between posts."""
    conn = get_db()
    queued = conn.execute(
        """SELECT p.id FROM posts p
           WHERE p.status = 'queued'
           ORDER BY p.created_at ASC"""
    ).fetchall()
    conn.close()

    results = []
    for post in queued:
        success, msg = post_clip(post["id"])
        results.append({"post_id": post["id"], "success": success, "message": msg})
        if success:
            time.sleep(5)  # Small delay between posts

    return results
