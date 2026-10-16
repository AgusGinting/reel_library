"""Tahap 1 — Kumpulkan shortcode reel dari DM Instagram.

Metode: menyadap respons JSON Instagram (network interception) lalu mengekstrak
shortcode. Reel yang di-share di DM TIDAK dirender sebagai <a href>, jadi metode
ini jauh lebih andal daripada membaca link di DOM.

Cara pakai:
  1. Jalankan file ini (profil browser sama, sesi login tersimpan).
  2. Buka DM berisi share reel, klik "Mulai Rekam".
  3. Scroll pelan ke atas. Shortcode tertangkap otomatis -> disimpan ke library.db.
  4. (Opsional) klik "Ekspor CSV" untuk melihat isinya.
"""

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import db
from config import PROFILE

# Pola ekstraksi shortcode dari body respons JSON.
CODE_PATTERNS = [
    re.compile(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{5,})"'),
    re.compile(r'"code"\s*:\s*"([A-Za-z0-9_-]{5,})"'),
]
PATH_PATTERN = re.compile(r'/(?:reel|reels|p)/([A-Za-z0-9_-]{5,})')

# Kata yang bukan shortcode (muncul di path UI/route Instagram).
RESERVED = {
    "audio", "reel", "reels", "explore", "stories", "direct", "accounts",
    "about", "developer", "privacy", "terms", "explore", "tv", "live",
}
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid_shortcode(code, source_path=""):
    """Shortcode reel/post Instagram modern = 11 karakter base64url.
    Saring kata route (mis. 'audio') dan token terlalu pendek."""
    if not code or code.lower() in RESERVED:
        return False
    if len(code) < 9:            # reel asli 11 char; <9 hampir pasti sampah
        return False
    if not SHORTCODE_RE.match(code):
        return False
    # Route-definitions sering memuat kata sampah; tolak yang bukan shortcode.
    if "bulk-route-definitions" in source_path and len(code) < 11:
        return False
    return True


class ReelCollector:
    def __init__(self, root):
        self.root = root
        self.root.title("Reel Collector")
        self.root.geometry("680x460")

        self.events = queue.Queue()
        self.recording = threading.Event()
        self.shutdown = threading.Event()
        self.export_now = threading.Event()

        self.ready = False
        self.closing = False
        self.seen = set()        # shortcode yang sudah dikirim ke DB sesi ini

        db.init_db()

        self.status = tk.StringVar(value="Menyiapkan browser...")
        self.total = tk.StringVar(value=f"Total reel di perpustakaan: {db.total()}")

        self._build_ui()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.after(200, self._pump)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Reel Collector",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(main, wraplength=630, text=(
            "Login, buka DM berisi share reel, klik 'Mulai Rekam', lalu scroll "
            "pelan ke atas. Shortcode tersimpan otomatis ke library.db."
        )).pack(anchor="w", pady=(6, 12))

        ttk.Label(main, textvariable=self.status,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(main, textvariable=self.total).pack(anchor="w", pady=(4, 12))

        row = ttk.Frame(main)
        row.pack(anchor="w", pady=(0, 10))
        self.start_btn = ttk.Button(row, text="Mulai Rekam",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(row, text="Berhenti", command=self.stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.export_btn = ttk.Button(row, text="Ekspor CSV",
                                     command=lambda: self.export_now.set(),
                                     state="disabled")
        self.export_btn.pack(side="left")

        ttk.Label(main, text="Log:").pack(anchor="w")
        self.log_box = tk.Text(main, height=12, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start(self):
        self.recording.set()
        self.status.set("MEREKAM — scroll pelan di DM...")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def stop(self):
        self.recording.clear()
        self.status.set("Berhenti. Browser tetap terbuka.")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def close_app(self):
        if self.closing:
            return
        self.closing = True
        self.shutdown.set()
        self.status.set("Menutup...")

    def _worker(self):
        try:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE),
                    headless=False,
                    viewport={"width": 1365, "height": 900},
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                ctx.on("response", self._on_response)

                if not page.url.startswith("http"):
                    page.goto("https://www.instagram.com/direct/inbox/",
                              wait_until="domcontentloaded", timeout=60000)

                self.events.put(("ready", None))

                while not self.shutdown.is_set():
                    try:
                        page.wait_for_timeout(500)   # memompa event 'response'
                    except Exception:
                        pass
                    if self.export_now.is_set():
                        self.export_now.clear()
                        n = db.export_csv()
                        self.events.put(("log", f"Ekspor CSV: {n} baris."))

                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception as exc:
            self.events.put(("fatal", str(exc)))
        finally:
            self.events.put(("finished", None))

    def _on_response(self, response):
        if not self.recording.is_set():
            return
        try:
            host = (urlparse(response.url).hostname or "").lower()
            if "instagram.com" not in host:
                return
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" not in ctype and "javascript" not in ctype:
                return

            body = response.text()
            path = urlparse(response.url).path

            codes = set()
            for pat in CODE_PATTERNS:
                codes.update(pat.findall(body))
            codes.update(PATH_PATTERN.findall(body))

            fresh = []
            for code in codes:
                if code in self.seen or not is_valid_shortcode(code, path):
                    continue
                self.seen.add(code)
                fresh.append({
                    "shortcode": code,
                    "url": f"https://www.instagram.com/reel/{code}/",
                    "first_seen": db.now(),
                })

            if fresh:
                added = db.add_collected(fresh)
                if added:
                    self.events.put(("found", (added, db.total())))
        except Exception:
            pass   # body tak terbaca / respons kedaluwarsa — abaikan

    def _pump(self):
        try:
            while True:
                ev, data = self.events.get_nowait()
                if ev == "ready":
                    self.ready = True
                    self.status.set("Browser siap. Buka DM lalu 'Mulai Rekam'.")
                    self.start_btn.configure(state="normal")
                    self.export_btn.configure(state="normal")
                    self.log("Browser siap.")
                elif ev == "found":
                    added, tot = data
                    self.total.set(f"Total reel di perpustakaan: {tot}")
                    self.log(f"+{added} reel baru. Total: {tot}.")
                elif ev == "log":
                    self.log(data)
                elif ev == "fatal":
                    self.status.set("Browser gagal.")
                    self.log(f"ERROR: {data}")
                elif ev == "finished":
                    self.status.set("Selesai.")
        except queue.Empty:
            pass

        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(200, self._pump)


if __name__ == "__main__":
    root = tk.Tk()
    ReelCollector(root)
    root.mainloop()
