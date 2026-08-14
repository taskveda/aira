import threading
import time
from datetime import datetime

from croniter import croniter

from .brain import Brain


class Scheduler:
    def __init__(self, config, brain_factory, session_factory):
        self.config = config
        self.brain_factory = brain_factory
        self.session_factory = session_factory
        self._running = True

    def run(self):
        # Store each job's *next scheduled* time. Fire exactly when `now`
        # reaches it, then advance to the following occurrence. This runs a job
        # once per cron occurrence (the original code never fired at all).
        next_times = {}
        while self._running:
            now = datetime.now()
            self._check_reminders()
            for job in self.config.get("jobs", []):
                expr = job.get("cron")
                name = job.get("name") or expr
                if not expr:
                    continue
                if name not in next_times:
                    next_times[name] = croniter(expr, now).get_next(datetime)
                if now >= next_times[name]:
                    threading.Thread(target=self._execute, args=(job,), daemon=True).start()
                    next_times[name] = croniter(expr, next_times[name]).get_next(datetime)
            time.sleep(30)

    def _check_reminders(self):
        """Surface any due reminders to the digest channel (once)."""
        try:
            from . import productivity
            due = productivity.reminder_due()
            if not due:
                return
            channel = self.config.digest_channel()
            session = self.session_factory(channel)
            for r in due:
                session.post_text(f"*⏰ Reminder:* {r['text']}  (due {r['due_at']})")
        except Exception as exc:
            print(f"[aira] reminder check error: {exc}")

    def _execute(self, job):
        try:
            if job.get("type") == "automation":
                from .automation import run_automation
                res = run_automation(self.config, job.get("action", ""), n=job.get("count", 5))
                channel = job.get("channel") or self.config.digest_channel()
                status = "done" if res.get("ok") else f"FAILED: {res.get('error')}"
                session = self.session_factory(channel)
                session.post_text(f"*Scheduled automation: {job.get('action', job.get('name'))}*\n{status}")
                return
            channel = job.get("channel") or self.config.digest_channel()
            session = self.session_factory(channel)
            from .executor import ToolExecutor
            executor = ToolExecutor(session, self.config)
            brain = self.brain_factory(executor)
            reply = brain.run([{"role": "user", "content": job.get("task", "")}])
            session.post_text(f"*Scheduled: {job.get('name')}*\n{reply}")
        except Exception as exc:
            print(f"[aira] job error: {exc}")
