"""
ClipForge — YouTube Content Automation System
Main Flask Application
"""
import os
from flask import Flask, render_template, send_from_directory
from models import init_db
from routes.api import api
from config import SECRET_KEY, DEBUG, HOST, PORT, CLIPS_DIR, THUMBNAILS_DIR


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # Initialize database
    init_db()

    # Register API blueprint
    app.register_blueprint(api)

    # ─── Page Routes ─────────────────────────────────────

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html", page="dashboard")

    @app.route("/channels")
    def channels():
        return render_template("channels.html", page="channels")

    @app.route("/videos")
    def videos():
        return render_template("videos.html", page="videos")

    @app.route("/clips")
    def clips():
        return render_template("clips.html", page="clips")

    @app.route("/posts")
    def posts():
        return render_template("posts.html", page="posts")

    @app.route("/accounts")
    def accounts():
        return render_template("accounts.html", page="accounts")

    @app.route("/settings")
    def settings():
        return render_template("settings.html", page="settings")

    # ─── Media Serving ───────────────────────────────────

    @app.route("/media/clips/<path:filename>")
    def serve_clip(filename):
        return send_from_directory(CLIPS_DIR, filename)

    @app.route("/media/thumbnails/<path:filename>")
    def serve_thumbnail(filename):
        return send_from_directory(THUMBNAILS_DIR, filename)

    return app


if __name__ == "__main__":
    app = create_app()

    # Start background scheduler
    try:
        from engine.scheduler import start_scheduler
        start_scheduler()
        print("\n⚡ ClipForge Scheduler started!")
    except Exception as e:
        print(f"\n⚠️  Scheduler failed to start: {e}")

    print(f"\n{'='*50}")
    print(f"  ⚡ ClipForge is running!")
    print(f"  📊 Dashboard: http://localhost:{PORT}")
    print(f"  📡 API:       http://localhost:{PORT}/api")
    print(f"{'='*50}\n")

    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
