import csv
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

# Semua file disimpan di folder aplikasi.
BASE = Path(__file__).resolve().parent
PROFILE = BASE / "browser_profile"
OUTPUT = BASE / "reels.csv"

REEL_PATTERN = re.compile(
    r"^/(reel|reels|p)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def normalize_instagram_url(raw_url):
    """Normalisasi URL Reel/post tanpa query atau fragmen."""
    try:
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").lower()

        if host not in {"instagram.com", "www.instagram.com"}:
            return None

        match = REEL_PATTERN.match(parsed.path)
        if not match:
            return None

        kind, code = match.groups()
        return f"https://www.instagram.com/{kind.lower()}/{code}/"

    except (ValueError, AttributeError):
        return None


def load_results():
    results = {}

    if OUTPUT.exists():
        try:
            with OUTPUT.open("r", newline="", encoding="utf-8-sig") as file:
                for row in csv.DictReader(file):
                    url = row.get("url", "")
                    if url:
                        results[url] = {
                            "url": url,
                            "first_seen": row.get("first_seen", ""),
                            "status": row.get("status", "link_found"),
                        }
        except (OSError, csv.Error) as exc:
            raise RuntimeError(f"Tidak bisa membaca {OUTPUT}: {exc}") from exc

    return results


def save_results(results):
    """Tulis ke file sementara, lalu ganti file CSV."""
    temp_file = OUTPUT.with_suffix(".tmp")

    with temp_file.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["url", "first_seen", "status"],
        )
        writer.writeheader()
        writer.writerows(results.values())

    temp_file.replace(OUTPUT)


class ReelCollectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Reel Knowledge Collector")
        self.root.geometry("650x430")
        self.root.minsize(560, 360)

        self.events = queue.Queue()
        self.recording = threading.Event()
        self.shutdown = threading.Event()

        self.browser_ready = False
        self.closing = False
        self.worker = None
        self.results = {}

        BASE.mkdir(parents=True, exist_ok=True)

        try:
            self.results = load_results()
        except RuntimeError as exc:
            messagebox.showerror("File error", str(exc))
            root.destroy()
            return

        self.status = tk.StringVar(value="Menyiapkan browser...")
        self.total = tk.StringVar(value=f"Total link tersimpan: {len(self.results)}")

        self.build_ui()
        self.set_buttons()

        self.worker = threading.Thread(
            target=self.browser_worker,
            daemon=True,
        )
        self.worker.start()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.after(200, self.process_events)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(
            main,
            text="Reel Knowledge Collector",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            main,
            text=(
                "Login sendiri, buka DM, lalu gulir ke pesan lama. "
                "Aplikasi hanya merekam tautan yang ditemukan."
            ),
            wraplength=590,
        ).pack(anchor="w", pady=(8, 14))

        ttk.Label(
            main,
            textvariable=self.status,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            main,
            textvariable=self.total,
        ).pack(anchor="w", pady=(4, 12))

        buttons = ttk.Frame(main)
        buttons.pack(anchor="w", pady=(0, 12))

        self.start_button = ttk.Button(
            buttons,
            text="Mulai Rekam",
            command=self.start_recording,
        )
        self.start_button.pack(side="left", padx=(0, 8))

        self.stop_button = ttk.Button(
            buttons,
            text="Berhenti Rekam",
            command=self.stop_recording,
        )
        self.stop_button.pack(side="left", padx=(0, 8))

        self.close_button = ttk.Button(
            buttons,
            text="Tutup Aplikasi",
            command=self.close_app,
        )
        self.close_button.pack(side="left")

        ttk.Label(
            main,
            text=f"Lokasi hasil: {OUTPUT}",
            wraplength=590,
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            main,
            text=(
                "Privasi: aplikasi tidak membaca atau menulis clipboard. "
                "Profil browser tetap tersimpan secara lokal."
            ),
            wraplength=590,
        ).pack(anchor="w", pady=(0, 10))

        ttk.Label(main, text="Log aktivitas:").pack(anchor="w")

        self.log_box = tk.Text(
            main,
            height=9,
            wrap="word",
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))

    def log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_buttons(self):
        ready = self.browser_ready and not self.closing
        active = self.recording.is_set()

        self.start_button.configure(
            state="normal" if ready and not active else "disabled"
        )
        self.stop_button.configure(state="normal" if ready and active else "disabled")
        self.close_button.configure(state="disabled" if self.closing else "normal")

    def start_recording(self):
        if not self.browser_ready or self.closing:
            return

        self.recording.set()
        self.status.set("MEREKAM — mengumpulkan link Reel...")
        self.log("Rekaman dimulai.")
        self.set_buttons()

    def stop_recording(self):
        self.recording.clear()
        self.status.set("Berhenti merekam. Browser tetap terbuka.")
        self.log("Rekaman dihentikan. Link yang terkumpul tetap disimpan.")
        self.set_buttons()

    def close_app(self):
        if self.closing:
            return

        self.closing = True
        self.recording.clear()
        self.shutdown.set()
        self.status.set("Menutup browser dengan aman...")
        self.set_buttons()

    def browser_worker(self):
        context = None

        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE),
                    headless=False,
                    viewport={"width": 1365, "height": 900},
                )

                pages = context.pages
                page = pages[0] if pages else context.new_page()

                if not page.url.startswith("http"):
                    page.goto(
                        "https://www.instagram.com/",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                self.events.put(("ready", None))

                while not self.shutdown.wait(0.5):
                    if not self.recording.is_set():
                        continue

                    try:
                        # Ambil tab Instagram yang masih terbuka.
                        pages = [
                            tab
                            for tab in context.pages
                            if "instagram.com" in urlparse(tab.url).netloc.lower()
                        ]

                        if not pages:
                            continue

                        page = pages[-1]

                        # Navigasi dapat membatalkan evaluasi DOM.
                        # Jika terjadi, lewati siklus ini dan coba lagi.
                        links = page.locator("a[href]").evaluate_all(
                            "(elements) => elements.map(element => element.href)"
                        )

                        added = 0
                        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

                        for raw_link in links:
                            url = normalize_instagram_url(raw_link)

                            if not url or url in self.results:
                                continue

                            self.results[url] = {
                                "url": url,
                                "first_seen": timestamp,
                                "status": "link_found",
                            }
                            added += 1

                        if added:
                            save_results(self.results)
                            self.events.put(("found", (added, len(self.results))))

                    except Exception as exc:
                        # Navigasi, tab yang ditutup, atau DOM berubah
                        # tidak boleh mematikan keseluruhan aplikasi.
                        error_text = str(exc).lower()

                        expected_errors = (
                            "execution context was destroyed",
                            "target closed",
                            "frame was detached",
                            "navigation",
                        )

                        if any(err in error_text for err in expected_errors):
                            continue

                        self.events.put(
                            ("warning", "Pemindaian sementara gagal; mencoba lagi.")
                        )

                # Simpan sebelum browser ditutup.
                try:
                    save_results(self.results)
                except Exception as exc:
                    self.events.put(("error", f"Gagal menyimpan CSV: {exc}"))

                try:
                    context.close()
                except Exception:
                    # Browser mungkin sudah ditutup secara manual.
                    pass

        except Exception as exc:
            self.events.put(("fatal", str(exc)))

        finally:
            self.events.put(("finished", None))

    def process_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()

                if event == "ready":
                    self.browser_ready = True
                    self.status.set(
                        "Browser siap. Login lalu buka DM yang ingin dipindai."
                    )
                    self.log("Browser siap. Login dilakukan secara manual.")

                elif event == "found":
                    added, total = data
                    self.total.set(f"Total link tersimpan: {total}")
                    self.log(f"+{added} link baru. Total: {total}.")

                elif event == "warning":
                    self.log(data)

                elif event == "error":
                    self.log(data)

                elif event == "fatal":
                    self.status.set("Browser gagal dijalankan.")
                    self.log(f"ERROR: {data}")

                elif event == "finished":
                    self.browser_ready = False
                    self.recording.clear()
                    self.status.set("Aplikasi berhenti.")
                    self.set_buttons()

        except queue.Empty:
            pass

        self.set_buttons()

        if self.closing:
            if self.worker is None or not self.worker.is_alive():
                self.root.destroy()
                return

        self.root.after(200, self.process_events)


if __name__ == "__main__":
    root = tk.Tk()
    app = ReelCollectorApp(root)
    root.mainloop()
