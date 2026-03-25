"""
Auto Poster — posts clips to TikTok, Instagram, YouTube Shorts.
Uses Selenium for TikTok/Instagram, YouTube Data API for YouTube.
"""
import os
import time
import json
from datetime import datetime
from models import get_db, log_activity


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


def post_clip(post_id):
    """Post a clip from the queue."""
    conn = get_db()
    post = conn.execute(
        """SELECT p.*, c.file_path, c.title as clip_title
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
    caption = post["caption"] or f"{post['clip_title']} #shorts #viral #clips"

    if platform == "youtube":
        success, result = handler(clip_path, post["clip_title"], caption)
    else:
        success, result = handler(clip_path, caption)

    if success:
        conn.execute(
            """UPDATE posts SET status = 'posted', posted_at = ?, post_url = ?
               WHERE id = ?""",
            (datetime.utcnow().isoformat(), result, post_id)
        )
        log_activity("Post Success", f"{post['clip_title']} → {platform}", "success")
    else:
        conn.execute(
            "UPDATE posts SET status = 'failed', error_message = ? WHERE id = ?",
            (result, post_id)
        )
        log_activity("Post Failed", f"{post['clip_title']} → {platform}: {result}", "error")

    conn.commit()
    conn.close()
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
