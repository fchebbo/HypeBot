import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import os
import subprocess
import yt_dlp
from detector import detect_ko_events, cut_clips


class HypeBot(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HypeBot 🎮")
        self.geometry("600x500")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")
        self._build_ui()

    def _build_ui(self):
        # --- Title ---
        tk.Label(
            self,
            text="⚡ HypeBot",
            font=("Helvetica", 22, "bold"),
            bg="#1e1e1e",
            fg="#ff4444"
        ).pack(pady=(20, 4))

        tk.Label(
            self,
            text="Smash Ultimate Auto Clipper",
            font=("Helvetica", 11),
            bg="#1e1e1e",
            fg="#aaaaaa"
        ).pack(pady=(0, 20))

        # --- URL Input ---
        tk.Label(
            self,
            text="YouTube / Twitch URL:",
            font=("Helvetica", 10),
            bg="#1e1e1e",
            fg="#ffffff"
        ).pack(anchor="w", padx=30)

        self.url_entry = tk.Entry(
            self,
            width=68,
            font=("Helvetica", 10),
            bg="#2d2d2d",
            fg="#ffffff",
            insertbackground="white",
            relief="flat",
            bd=6
        )
        self.url_entry.pack(padx=30, pady=(4, 16))

        # --- Run Button ---
        self.run_btn = tk.Button(
            self,
            text="🎬  Generate Clips",
            font=("Helvetica", 12, "bold"),
            bg="#ff4444",
            fg="#ffffff",
            activebackground="#cc0000",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._start_pipeline
        )
        self.run_btn.pack(pady=(0, 16))

        # --- Progress Bar ---
        self.progress = ttk.Progressbar(
            self,
            mode="indeterminate",
            length=540
        )
        self.progress.pack(padx=30, pady=(0, 12))

        # --- Log Output ---
        tk.Label(
            self,
            text="Log:",
            font=("Helvetica", 10),
            bg="#1e1e1e",
            fg="#aaaaaa"
        ).pack(anchor="w", padx=30)

        self.log = scrolledtext.ScrolledText(
            self,
            height=12,
            font=("Courier", 9),
            bg="#2d2d2d",
            fg="#00ff88",
            insertbackground="white",
            relief="flat",
            bd=6,
            state="disabled"
        )
        self.log.pack(padx=30, pady=(4, 20), fill="x")

    def _log(self, message):
        """Append a line to the log box — safe to call from any thread."""
        def _append():
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _append)

    def _start_pipeline(self):
        url = self.url_entry.get().strip()
        if not url:
            self._log("⚠️  Please paste a URL first.")
            return

        self.run_btn.configure(state="disabled", text="Working...")
        self.progress.start(10)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        thread = threading.Thread(target=self._run_pipeline, args=(url,), daemon=True)
        thread.start()

    def _run_pipeline(self, url):
        try:
            self._log("📥  Downloading VOD...")
            video_path = self._download_vod(url)

            if not video_path:
                self._log("❌  Download failed — no file found.")
                return

            self._log(f"\n🔍  Scanning for KO flashes...")
            events = detect_ko_events(video_path)

            if not events:
                self._log("⚠️  No KO events detected. Try adjusting thresholds.")
                return

            self._log(f"\n✂️  Cutting {len(events)} clip(s)...")
            cut_clips(video_path, events)

            self._log(f"\n✅  Done! Opening clips folder...")
            self._open_clips_folder()

        except Exception as e:
            self._log(f"\n❌  Error: {e}")
        finally:
            self.after(0, self._pipeline_done)

    def _download_vod(self, url):
        """Download VOD using yt-dlp, logging progress to the UI."""
        os.makedirs("downloads", exist_ok=True)

        class YTLogger:
            def __init__(self, log_fn):
                self.log_fn = log_fn
            def debug(self, msg):
                if msg.startswith('[download]'):
                    self.log_fn(msg)
            def info(self, msg):
                self.log_fn(msg)
            def warning(self, msg):
                self.log_fn(f"⚠️  {msg}")
            def error(self, msg):
                self.log_fn(f"❌  {msg}")

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'logger': YTLogger(self._log),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        downloads = os.listdir("downloads")
        if downloads:
            return f"downloads/{downloads[0]}"
        return None

    def _open_clips_folder(self):
        clips_dir = os.path.abspath("clips")
        os.makedirs(clips_dir, exist_ok=True)
        subprocess.Popen(f'explorer "{clips_dir}"')

    def _pipeline_done(self):
        self.progress.stop()
        self.run_btn.configure(state="normal", text="🎬  Generate Clips")


if __name__ == "__main__":
    app = HypeBot()
    app.mainloop()