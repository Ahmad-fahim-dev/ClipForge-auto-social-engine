/* ═══════════════════════════════════════════════════════════
   ClipForge — Frontend JavaScript
   Theme Toggle • API Helper • SVG Toast Icons
   ═══════════════════════════════════════════════════════════ */

// ─── Theme ───────────────────────────────────────────────

function getTheme() {
    return localStorage.getItem('clipforge-theme') || 'dark';
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('clipforge-theme', theme);
}

function toggleTheme() {
    setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

// ─── API Helper ──────────────────────────────────────────

async function api(url, method = 'GET', body = null) {
    try {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        return await res.json();
    } catch (e) {
        console.error('API Error:', e);
        showToast('Network error — check the server', 'error');
        return null;
    }
}

// ─── Toast Notifications ─────────────────────────────────

const TOAST_ICONS = {
    success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#22C55E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    error: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    warning: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
};

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `${TOAST_ICONS[type] || TOAST_ICONS.info}<span style="flex:1;">${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(80px)';
        toast.style.transition = 'all 0.35s ease';
        setTimeout(() => toast.remove(), 350);
    }, 4500);
}

// ─── Modal ───────────────────────────────────────────────

function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.add('active');
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) e.target.classList.remove('active');
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
    }
});

// ─── Utilities ───────────────────────────────────────────

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function timeAgo(dateStr) {
    if (!dateStr) return 'N/A';
    const seconds = Math.floor((new Date() - new Date(dateStr)) / 1000);
    if (isNaN(seconds) || seconds < 0) return 'Just now';
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ─── Dashboard Stats ─────────────────────────────────────

async function loadStats() {
    const data = await api('/api/stats');
    if (!data) return;

    const map = {
        'stat-channels': data.total_channels,
        'stat-videos': data.total_videos,
        'stat-clips': data.total_clips,
        'stat-posted': data.posts_today,
        'stat-queue': data.queued_posts,
        'stat-pending': data.pending_downloads,
    };

    for (const [id, value] of Object.entries(map)) {
        const el = document.getElementById(id);
        if (el) {
            const current = parseInt(el.textContent) || 0;
            if (current !== value) {
                el.textContent = value;
                el.style.transform = 'scale(1.08)';
                el.style.transition = 'transform 0.25s ease';
                setTimeout(() => { el.style.transform = 'scale(1)'; }, 200);
            }
        }
    }

    const navChannels = document.getElementById('nav-channels-count');
    const navClips = document.getElementById('nav-clips-count');
    const navQueue = document.getElementById('nav-queue-count');
    if (navChannels) navChannels.textContent = data.total_channels;
    if (navClips) navClips.textContent = data.total_clips;
    if (navQueue) navQueue.textContent = data.queued_posts;
}

// ─── Activity Feed ───────────────────────────────────────

async function loadActivity() {
    const data = await api('/api/activity?limit=25');
    const feed = document.getElementById('activity-feed');
    if (!feed || !data) return;

    if (data.length === 0) {
        feed.innerHTML = `
            <li class="empty-state" style="padding:32px;">
                <div class="empty-icon-wrap">
                    <svg class="icon-svg xl" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                </div>
                <h3>No activity yet</h3>
                <p>Add some channels to get started</p>
            </li>`;
        return;
    }

    feed.innerHTML = data.map(a => `
        <li class="activity-item">
            <div class="activity-dot ${a.level}"></div>
            <div class="activity-text">
                <strong>${esc(a.action)}</strong><br>
                ${esc(a.details)}
            </div>
            <div class="activity-time">${timeAgo(a.created_at)}</div>
        </li>
    `).join('');
}

// ─── Global Actions ──────────────────────────────────────

async function checkChannels() {
    showToast('Checking channels for new videos...', 'info');
    const res = await api('/api/actions/check-channels', 'POST');
    if (res) {
        const msg = res.new_videos > 0
            ? `Found ${res.new_videos} new video(s)!`
            : 'No new videos found';
        showToast(msg, res.new_videos > 0 ? 'success' : 'info');
    }
    if (typeof loadStats === 'function') loadStats();
    if (typeof loadActivity === 'function') loadActivity();
}

async function downloadAll() {
    showToast('Downloading all pending videos...', 'info');
    await api('/api/actions/download-all', 'POST');
    showToast('Downloads processed!', 'success');
    if (typeof loadStats === 'function') loadStats();
}

// ─── Scheduler Status ────────────────────────────────────

async function updateSchedulerStatus() {
    const data = await api('/api/scheduler/status');
    const el = document.getElementById('scheduler-status');
    if (!el || !data) return;

    if (data.running) {
        el.innerHTML = `<div class="dot"></div><span>Automation Running</span>`;
        el.style.borderColor = 'rgba(34, 197, 94, 0.12)';
        el.style.background = 'rgba(34, 197, 94, 0.06)';
        el.style.color = 'var(--success)';
    } else {
        el.innerHTML = `<div class="dot" style="background:var(--warning);box-shadow:0 0 6px rgba(245,158,11,0.5);"></div><span>Automation Paused</span>`;
        el.style.borderColor = 'rgba(245, 158, 11, 0.12)';
        el.style.background = 'rgba(245, 158, 11, 0.06)';
        el.style.color = 'var(--warning)';
    }
}

// ─── Init ────────────────────────────────────────────────
updateSchedulerStatus();
setInterval(updateSchedulerStatus, 15000);
