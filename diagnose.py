"""Alat diagnosa + penangkap reel lewat respons jaringan Instagram.

Cara pakai:
1. Jalankan file ini (profil browser sama dengan app.py).
2. Login (kalau perlu), buka DM yang berisi share reel.
3. Klik "Mulai Tangkap", lalu scroll pelan ke atas di chat.
4. Klik "Tulis Laporan" kapan saja untuk menyimpan hasil.
   File laporan: diagnostic_report.txt  dan  captured_reels.csv

Metode: menyadap setiap respons JSON dari instagram dan mengekstrak
shortcode reel/post. Jauh lebih andal daripada membaca <a href>.
"""

import csv
import json
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
PROFILE = BASE / "browser_profile"
REPORT = BASE / "diagnostic_report.txt"
CSV_OUT = BASE / "captured_reels.csv"

# Shortcode reel/post biasanya muncul sebagai "code":"..." atau "shortcode":"..."
CODE_PATTERNS = [
    re.compile(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{5,})"'),
    re.compile(r'"code"\s*:\s*"([A-Za-z0-9_-]{5,})"'),
]
# Pola path untuk jaga-jaga kalau URL reel ada di dalam body.
PATH_PATTERN = re.compile(r'/(reel|reels|p)/([A-Za-z0-9_-]{5,})')


class Diagnoser:
    def __init__(self, root):
        self.root = root
        self.root.title("Diagnosa Penangkap Reel")
        self.root.geometry("680x460")

        self.events = queue.Queue()
        self.capturing = threading.Event()
        self.shutdown = threading.Event()
        self.dump_now = threading.Event()

        self.ready = False
        self.closing = False

        # shortcode -> dict(code, source_url, pattern, first_seen)
        self.found = {}
        # Statistik endpoint: url -> jumlah respons JSON instagram
        self.endpoints = {}

        self.status = tk.StringVar(value="Menyiapkan browser...")
        self.total = tk.StringVar(value="Reel tertangkap: 0")

        self._build_ui()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.after(200, self._pump)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Diagnosa Penangkap Reel (via jaringan)",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(main, wraplength=630, text=(
            "Login, buka DM berisi share reel, klik 'Mulai Tangkap', "
            "lalu scroll pelan ke atas. Hasil disimpan ke captured_reels.csv "
            "dan diagnostic_report.txt."
        )).pack(anchor="w", pady=(6, 12))

        ttk.Label(main, textvariable=self.status,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(main, textvariable=self.total).pack(anchor="w", pady=(4, 12))

        row = ttk.Frame(main)
        row.pack(anchor="w", pady=(0, 10))
        self.start_btn = ttk.Button(row, text="Mulai Tangkap",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(row, text="Jeda", command=self.stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.dump_btn = ttk.Button(row, text="Tulis Laporan",
                                   command=lambda: self.dump_now.set(),
                                   state="disabled")
        self.dump_btn.pack(side="left")

        ttk.Label(main, text="Log:").pack(anchor="w")
        self.log_box = tk.Text(main, height=12, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start(self):
        self.capturing.set()
        self.status.set("MENANGKAP — scroll pelan di DM...")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def stop(self):
        self.capturing.clear()
        self.status.set("Dijeda. Browser tetap terbuka.")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def close_app(self):
        if self.closing:
            return
        self.closing = True
        self.shutdown.set()
        self.status.set("Menutup...")

    # --- worker thread (Playwright) ---
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
                    # Memanggil API Playwright memompa event 'response'.
                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
                    if self.dump_now.is_set():
                        self.dump_now.clear()
                        self._write_report(ctx)

                self._write_report(ctx)
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception as exc:
            self.events.put(("fatal", str(exc)))
        finally:
            self.events.put(("finished", None))

    def _on_response(self, response):
        if not self.capturing.is_set():
            return
        try:
            url = response.url
            host = (urlparse(url).hostname or "").lower()
            if "instagram.com" not in host:
                return
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" not in ctype and "javascript" not in ctype:
                return

            body = response.text()
            self.endpoints[self._endpoint_key(url)] = (
                self.endpoints.get(self._endpoint_key(url), 0) + 1
            )

            added = 0
            for pat in CODE_PATTERNS:
                for code in pat.findall(body):
                    if self._add(code, url, pat.pattern):
                        added += 1
            for _, code in PATH_PATTERN.findall(body):
                if self._add(code, url, "path"):
                    added += 1

            if added:
                self.events.put(("found", (added, len(self.found))))
        except Exception:
            # Body tak terbaca / respons sudah lewat — abaikan.
            pass

    @staticmethod
    def _endpoint_key(url):
        p = urlparse(url)
        return f"{p.path}"

    def _add(self, code, url, pattern):
        if code in self.found:
            return False
        self.found[code] = {
            "shortcode": code,
            "source_path": urlparse(url).path,
            "matched_by": pattern[:40],
            "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return True

    def _write_report(self, ctx):
        # CSV reel tertangkap
        try:
            with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "shortcode", "url", "source_path", "matched_by", "first_seen"])
                w.writeheader()
                for item in self.found.values():
                    w.writerow({
                        "shortcode": item["shortcode"],
                        "url": f"https://www.instagram.com/reel/{item['shortcode']}/",
                        "source_path": item["source_path"],
                        "matched_by": item["matched_by"],
                        "first_seen": item["first_seen"],
                    })
        except Exception as exc:
            self.events.put(("log", f"Gagal tulis CSV: {exc}"))

        # Analisa DOM halaman aktif (apa yang dilihat metode <a href> lama)
        dom_info = {}
        try:
            pages = [t for t in ctx.pages if "instagram.com" in (
                urlparse(t.url).hostname or "")]
            if pages:
                dom_info = pages[-1].evaluate(DOM_ANALYSIS_JS)
        except Exception as exc:
            dom_info = {"error": str(exc)}

        # Tulis laporan teks
        lines = []
        lines.append("=== LAPORAN DIAGNOSA PENANGKAP REEL ===")
        lines.append(f"Waktu: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Total reel tertangkap (jaringan): {len(self.found)}")
        lines.append("")
        lines.append("--- Endpoint JSON instagram yang terlihat (path: jumlah) ---")
        for path, n in sorted(self.endpoints.items(), key=lambda x: -x[1]):
            lines.append(f"  {n:4d}  {path}")
        lines.append("")
        lines.append("--- Shortcode tertangkap (maks 60) ---")
        for item in list(self.found.values())[:60]:
            lines.append(f"  {item['shortcode']}  via={item['matched_by']}  "
                         f"src={item['source_path']}")
        lines.append("")
        lines.append("--- Analisa DOM (metode <a href> lama) ---")
        lines.append(json.dumps(dom_info, indent=2, ensure_ascii=False))

        try:
            REPORT.write_text("\n".join(lines), encoding="utf-8")
            self.events.put(("log", f"Laporan ditulis: {len(self.found)} reel -> {REPORT.name}"))
        except Exception as exc:
            self.events.put(("log", f"Gagal tulis laporan: {exc}"))

    # --- UI pump ---
    def _pump(self):
        try:
            while True:
                ev, data = self.events.get_nowait()
                if ev == "ready":
                    self.ready = True
                    self.status.set("Browser siap. Buka DM lalu klik 'Mulai Tangkap'.")
                    self.start_btn.configure(state="normal")
                    self.dump_btn.configure(state="normal")
                    self.log("Browser siap.")
                elif ev == "found":
                    added, total = data
                    self.total.set(f"Reel tertangkap: {total}")
                    self.log(f"+{added} shortcode baru. Total: {total}.")
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


DOM_ANALYSIS_JS = r"""
() => {
  const out = {};
  const anchors = [...document.querySelectorAll('a[href]')]
    .map(a => a.href)
    .filter(h => /\/(reel|reels|p)\/[A-Za-z0-9_-]+/.test(h));
  out.anchor_reel_hrefs = [...new Set(anchors)].slice(0, 40);
  out.anchor_reel_count = new Set(anchors).size;
  out.role_button_count = document.querySelectorAll('[role=button]').length;
  out.role_link_count = document.querySelectorAll('[role=link]').length;
  const attrHits = [];
  for (const el of document.querySelectorAll('*')) {
    for (const attr of el.attributes) {
      if (/\/(reel|reels|p)\//.test(attr.value)) {
        attrHits.push(el.tagName + '[' + attr.name + ']=' + attr.value.slice(0,120));
      }
    }
    if (attrHits.length > 30) break;
  }
  out.attr_hits = attrHits;
  return out;
}
"""


if __name__ == "__main__":
    root = tk.Tk()
    Diagnoser(root)
    root.mainloop()
