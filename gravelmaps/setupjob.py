"""Runs setup (pipeline.run) in a background thread for the app's setup screen, and keeps the
status that screen polls: the list of steps, which one is running, download progress, problems.
"""
import contextlib
import io
import threading
import time
import traceback

import requests

from . import pipeline


class _LastLine(io.TextIOBase):
    """Captures printed output, keeping the last line as the step's detail text."""

    def __init__(self, job):
        self.job = job

    def write(self, s):
        for line in s.replace("\r", "\n").split("\n"):
            if line.strip():
                self.job.detail = line.strip()
        return len(s)


class SetupJob(pipeline.Reporter):
    def __init__(self, regions, update_data=False, rebuild=False, on_done=None):
        self.regions = regions
        self.update_data, self.rebuild = update_data, rebuild
        self.on_done = on_done
        self.steps = [{"key": k, "title": t, "state": "todo"} for k, t in pipeline.steps(regions, update_data, rebuild)]
        self.current = None
        self.done_bytes = self.total_bytes = 0
        self.detail = ""
        self.warnings = []
        self.error = None
        self.finished = False
        self.started = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True, name="gravelmaps-setup")

    # ---- Reporter ----
    def step(self, key, title):
        for s in self.steps:
            if s["key"] == self.current:
                s["state"] = "done"
            if s["key"] == key:
                s["state"] = "running"
        self.current = key
        self.done_bytes = self.total_bytes = 0
        self.detail = ""

    def progress(self, done, total):
        self.done_bytes, self.total_bytes = done, total

    def warn(self, message):
        self.warnings.append(message)

    # ---- running ----
    def start(self):
        self.thread.start()
        return self

    def _run(self):
        try:
            with contextlib.redirect_stdout(_LastLine(self)):
                pipeline.run(self.regions, self.update_data, self.rebuild, report=self)
            for s in self.steps:
                s["state"] = "done"
            self.current = None
            if self.on_done:
                self.on_done(self.regions)
        except Exception as e:  # shown on the setup screen, which offers to try again
            traceback.print_exc()
            for s in self.steps:
                if s["state"] == "running":
                    s["state"] = "failed"
            self.error = _friendly(e)
        finally:
            self.finished = True

    @property
    def running(self):
        return self.thread.is_alive()

    def status(self):
        return {
            "regions": self.regions, "steps": self.steps, "current": self.current,
            "done_bytes": self.done_bytes, "total_bytes": self.total_bytes, "detail": self.detail,
            "warnings": self.warnings, "error": self.error, "finished": self.finished, "running": self.running,
        }


def _friendly(e):
    if isinstance(e, requests.ConnectionError):
        return ("Couldn't connect to the internet. Check your connection and try again; "
                "downloads pick up where they left off.")
    if isinstance(e, OSError) and e.errno == 28:
        return "Your disk is full. Free up some space and try again."
    return f"{type(e).__name__}: {e}"
