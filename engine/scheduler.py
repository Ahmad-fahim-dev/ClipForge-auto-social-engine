"""
Background Scheduler — runs monitoring, downloading, clipping, posting on a schedule.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from models import get_setting, log_activity

scheduler = BackgroundScheduler(daemon=True)
_running = False


def monitor_job():
    """Scheduled job to check channels for new videos."""
    try:
        from engine.monitor import check_all_channels
        check_all_channels()
    except Exception as e:
        log_activity("Scheduler Error", f"Monitor job: {str(e)}", "error")


def download_job():
    """Scheduled job to download pending videos."""
    try:
        from engine.downloader import download_pending
        download_pending()
    except Exception as e:
        log_activity("Scheduler Error", f"Download job: {str(e)}", "error")


def clip_job():
    """Scheduled job to process downloaded videos."""
    try:
        from engine.clipper import process_pending
        process_pending()
    except Exception as e:
        log_activity("Scheduler Error", f"Clip job: {str(e)}", "error")


def post_job():
    """Scheduled job to post queued clips."""
    try:
        auto_post = get_setting("auto_post", "false")
        if auto_post.lower() == "true":
            from engine.poster import post_queued
            post_queued()
    except Exception as e:
        log_activity("Scheduler Error", f"Post job: {str(e)}", "error")


def start_scheduler():
    """Start the background scheduler with configured intervals."""
    global _running
    if _running:
        return

    interval = int(get_setting("check_interval", "10"))
    post_delay = int(get_setting("post_delay", "30"))

    # Monitor channels every N minutes
    scheduler.add_job(
        monitor_job, IntervalTrigger(minutes=interval),
        id="monitor", replace_existing=True, name="Channel Monitor"
    )

    # Download pending videos every 2 minutes
    scheduler.add_job(
        download_job, IntervalTrigger(minutes=2),
        id="downloader", replace_existing=True, name="Video Downloader"
    )

    # Process clips every 3 minutes
    scheduler.add_job(
        clip_job, IntervalTrigger(minutes=3),
        id="clipper", replace_existing=True, name="Clip Generator"
    )

    # Post queued clips
    scheduler.add_job(
        post_job, IntervalTrigger(minutes=post_delay),
        id="poster", replace_existing=True, name="Auto Poster"
    )

    scheduler.start()
    _running = True
    log_activity("Scheduler Started", f"Monitor: {interval}min, Post: {post_delay}min", "info")


def stop_scheduler():
    """Stop the background scheduler."""
    global _running
    if _running:
        scheduler.shutdown(wait=False)
        _running = False
        log_activity("Scheduler Stopped", "", "info")


def update_scheduler():
    """Update scheduler intervals from settings without restarting all jobs."""
    if not _running:
        start_scheduler()
        return

    interval = int(get_setting("check_interval", "10"))
    post_delay = int(get_setting("post_delay", "30"))

    update_job_interval("monitor", interval)
    update_job_interval("poster", post_delay)


def update_job_interval(job_id, new_interval_minutes):
    """Reschedule a specific job with a new interval."""
    if not _running:
        return
    try:
        scheduler.reschedule_job(
            job_id,
            trigger=IntervalTrigger(minutes=new_interval_minutes)
        )
        log_activity("Job Rescheduled", f"{job_id}: {new_interval_minutes}min", "info")
    except Exception as e:
        log_activity("Scheduler Error", f"Failed to reschedule {job_id}: {str(e)}", "error")


def get_scheduler_status():
    """Get status of all scheduled jobs."""
    jobs = []
    if _running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else "N/A",
            })
    return {"running": _running, "jobs": jobs}
