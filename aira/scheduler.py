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
        while self._running:
            now = datetime.now()
            for job in self.config.get("jobs", []):
                expr = job.get("cron")
                if not expr:
                    continue
                it = croniter(expr, now)
                next_run = it.get_next(datetime)
                if next_run <= now:
                    threading.Thread(target=self._execute, args=(job,), daemon=True).start()
                    it = croniter(expr, now)
            time.sleep(30)

    def _execute(self, job):
        try:
            if job.get("type") == "automation":
                from .automation import run_automation
                res = run_automation(self.config, job.get("name", ""), n=job.get("count", 5))
                channel = job.get("channel") or self.config.digest_channel()
                status = "done" if res.get("ok") else f"FAILED: {res.get('error')}"
                session = self.session_factory(channel)
                session.post_text(f"*Scheduled automation: {job.get('name')}*\n{status}")
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
