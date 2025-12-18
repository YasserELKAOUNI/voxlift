#!/usr/bin/env python3
import os
import re
import subprocess
import threading
from pathlib import Path

import rumps


YOUTUBE_RE = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/")


class YWWMenu(rumps.App):
    def __init__(self):
        super().__init__("YWW", icon=None, menu=[
            rumps.MenuItem("Transcribe Clipboard URL", callback=self.transcribe_clipboard),
            rumps.MenuItem("Open Transcripts", callback=self.open_transcripts),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ])
        self.title = "YWW"
        self.out_dir = os.path.expanduser("~/Documents/Transcripts")
        os.makedirs(self.out_dir, exist_ok=True)
        # Resolve project paths (runs from repo)
        self.repo = Path(__file__).resolve().parents[1]
        self.venv_python = self.repo / ".venv/bin/python"
        self.src_path = self.repo / "src"

    def notify(self, title: str, subtitle: str = "", message: str = ""):
        rumps.notification(title, subtitle, message)

    def open_transcripts(self, _):
        subprocess.Popen(["open", self.out_dir])

    def quit_app(self, _):
        rumps.quit_application()

    def transcribe_clipboard(self, _):
        # Read clipboard
        try:
            url = subprocess.check_output(["pbpaste"]).decode("utf-8").strip()
        except Exception:
            self.notify("YWW", message="Cannot read clipboard")
            return
        if not url or not YOUTUBE_RE.search(url):
            self.notify("YWW", message="Clipboard does not contain a YouTube URL")
            return

        def worker():
            self.title = "YWW • Working…"
            try:
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.src_path)
                cmd = [str(self.venv_python), "-m", "yww.cli", "process", "--url", url,
                       "--out", self.out_dir, "--model", "base", "--lang", "auto"]
                # Show minimal progress in the menu title via --json if desired
                proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                last_line = None
                for line in proc.stdout or []:
                    last_line = line.strip()
                rc = proc.wait()
                if rc == 0:
                    self.notify("YWW", message="Transcript ready")
                else:
                    self.notify("YWW", message=f"Failed ({rc})")
            except Exception as e:
                self.notify("YWW", message=str(e))
            finally:
                self.title = "YWW"

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    YWWMenu().run()

