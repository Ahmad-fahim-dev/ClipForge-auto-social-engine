"""
In-memory rate limiting middleware for ClipForge.
Tracks requests per IP address and returns 429 when limits are exceeded.
"""
import time
from collections import defaultdict
from flask import request, jsonify

# ─── Rate Limit Configuration ────────────────────────────────────────────

GENERAL_RATE_LIMIT = 60       # requests per minute for general endpoints
ACTION_RATE_LIMIT = 10        # requests per minute for /api/actions/* endpoints
WINDOW = 60                   # time window in seconds

# ─── In-Memory Request Tracker ───────────────────────────────────────────

_request_counts = defaultdict(list)


def _cleanup_old_entries(ip, now):
    """Remove entries older than the time window."""
    _request_counts[ip] = [
        t for t in _request_counts[ip] if now - t < WINDOW
    ]


def check_rate_limit():
    """
    Check if the current request exceeds the rate limit.
    Returns None if allowed, or a Flask response (429) if exceeded.
    """
    ip = request.remote_addr or "unknown"
    now = time.time()

    _cleanup_old_entries(ip, now)

    # Determine which limit applies
    if request.path.startswith("/api/actions"):
        limit = ACTION_RATE_LIMIT
    else:
        limit = GENERAL_RATE_LIMIT

    if len(_request_counts[ip]) >= limit:
        return jsonify({
            "error": "Rate limit exceeded. Please try again later.",
            "limit": limit,
            "window_seconds": WINDOW
        }), 429

    _request_counts[ip].append(now)
    return None
