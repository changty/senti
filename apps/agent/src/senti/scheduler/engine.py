"""APScheduler setup with AsyncIOScheduler."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """Wraps APScheduler's AsyncIOScheduler."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def start(self) -> None:
        """Start the scheduler."""
        if not self._running:
            self._scheduler.start()
            self._running = True
            logger.info("Scheduler started")

    def pause(self) -> None:
        """Pause all jobs."""
        if self._running:
            self._scheduler.pause()
            logger.info("Scheduler paused")

    def resume(self) -> None:
        """Resume all jobs."""
        if self._running:
            self._scheduler.resume()
            logger.info("Scheduler resumed")

    def shutdown(self) -> None:
        """Shut down the scheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler shut down")

    def get_jobs_info(self) -> str:
        """Return human-readable info about scheduled jobs."""
        jobs = self._scheduler.get_jobs()
        if not jobs:
            return "No scheduled jobs."

        lines = []
        for job in jobs:
            next_run = job.next_run_time
            status = f"next: {next_run}" if next_run else "paused"
            lines.append(f"- {job.name}: {status}")
        return "\n".join(lines)
