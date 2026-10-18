"""Login ulang Instagram untuk aplikasi ini (dipakai saat sesi habis).

Membuka jendela Chromium dengan profil aplikasi (browser_profile/) di halaman login
Instagram. Begitu login berhasil (cookie `sessionid` muncul), cookies diekspor ke
cookies.txt dan jendela ditutup otomatis. Batas waktu 10 menit.

    python login.py

Bisa juga dijalankan dari web: tombol "Login Instagram" di jendela "Tambah materi".
Tutup collect.py dulu bila sedang terbuka (profil browser tidak bisa dipakai bersamaan).
"""

import sys
import time

from playwright.sync_api import sync_playwright

import download
from config import PROFILE

TIMEOUT_S = 600


def has_session(ctx):
    return any(c["name"] == "sessionid" and c["value"] and "instagram.com" in c["domain"]
               for c in ctx.cookies())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), headless=False,
            viewport={"width": 1100, "height": 850})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if has_session(ctx):
            print("Sudah login Instagram.")
        else:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
            print("Silakan login Instagram di jendela browser yang terbuka...")
            deadline = time.time() + TIMEOUT_S
            while not has_session(ctx):
                if time.time() > deadline:
                    print("Waktu habis, login tidak terdeteksi.")
                    ctx.close()
                    sys.exit(1)
                try:
                    page.wait_for_timeout(1500)
                except Exception:   # jendela ditutup pengguna
                    print("Jendela ditutup sebelum login selesai.")
                    sys.exit(1)
            print("Login berhasil.")
            page.wait_for_timeout(2000)   # beri waktu Instagram menulis cookie lain
        ctx.close()

    n = download.export_cookies()
    ok = download.instagram_logged_in()
    print(f"Cookies diekspor ({n}). Status sesi: {'OK' if ok else 'BELUM LOGIN'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
