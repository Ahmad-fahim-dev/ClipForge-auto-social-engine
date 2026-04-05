"""
ClipForge — YouTube Content Automation System
Main Flask Application
"""
import os
import signal
import atexit
from flask import Flask, render_template, send_from_directory, request
from models import init_db
from routes.api import api
from config import SECRET_KEY, DEBUG, HOST, PORT, CLIPS_DIR, THUMBNAILS_DIR
from middleware import check_rate_limit


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

    # Initialize database
    init_db()

    # Register API blueprint
    app.register_blueprint(api)

    # ─── Security Middleware ─────────────────────────────────────────

    @app.before_request
    def rate_limit():
        """Apply rate limiting to all requests."""
        return check_rate_limit()

    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses."""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://img.youtube.com; "
            "media-src 'self'; "
            "connect-src 'self'"
        )
        return response

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
        from engine.scheduler import start_scheduler, stop_scheduler
        start_scheduler()
        print("\n[OK] ClipForge Scheduler started!")
    except Exception as e:
        print(f"\n[WARN] Scheduler failed to start: {e}")
        stop_scheduler = lambda: None

    def graceful_shutdown(signum=None, frame=None):
        print("\nShutting down ClipForge...")
        stop_scheduler()
        import sys
        sys.exit(0)

    atexit.register(stop_scheduler)
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    print(f"\n{'='*50}")
    print(f"  ClipForge is running!")
    print(f"  Dashboard: http://localhost:{PORT}")
    print(f"  API:       http://localhost:{PORT}/api")
    print(f"{'='*50}\n")

    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
