"""Tahap 2 — Unduh video + metadata tiap reel (yt-dlp).

Alur:
  1. Ekspor cookies dari browser_profile (sesi login) -> cookies.txt
     supaya reel dari akun privat/terbatas tetap bisa diunduh.
  2. Untuk tiap reel status='collected', unduh video + thumbnail + metadata
     ke data/<shortcode>/, lalu update DB -> status='downloaded'.
  3. Jeda acak antar unduhan agar tidak diblokir Instagram.

Jalankan di terminal:
    python download.py             # unduh semua yang belum terunduh
    python download.py --limit 3   # uji beberapa dulu
    python download.py --cookies   # hanya segarkan cookies.txt lalu keluar

Catatan: tutup collect.py dulu (profil browser tidak boleh dipakai bersamaan).
"""

import argparse
import random
import http.cookiejar
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

import yt_dlp
from playwright.sync_api import sync_playwright

import db
import tiktok
from config import (BASE, PROFILE, DATA, DOWNLOAD_DELAY_MIN,
                    DOWNLOAD_DELAY_MAX)

COOKIES = BASE / "cookies.txt"


def _netscape_line(c):
    domain = c["domain"]
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    secure = "TRUE" if c.get("secure") else "FALSE"
    expires = int(c.get("expires") or 0)
    if expires < 0:
        expires = 0
    return "\t".join([domain, flag, c.get("path", "/"), secure,
                      str(expires), c["name"], c["value"]])


def export_cookies():
    """Baca cookies Instagram dari profil Playwright -> cookies.txt (Netscape)."""
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), headless=True)
        cookies = ctx.cookies()
        ctx.close()

    ig = [c for c in cookies if "instagram.com" in c.get("domain", "")]
    lines = ["# Netscape HTTP Cookie File", ""]
    lines += [_netscape_line(c) for c in ig]
    COOKIES.write_text("\n".join(lines), encoding="utf-8")
    print(f"Cookies diekspor: {len(ig)} cookie instagram -> {COOKIES.name}")
    return len(ig)


class NoVideoFile(Exception):
    """Unduhan selesai tetapi tidak ada file video (hanya audio/gambar)."""


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _find_video(folder):
    return next((p for p in folder.glob("video.*")
                 if p.suffix.lower() in VIDEO_EXTS), None)


def _find_thumb(folder):
    return next((p for p in folder.glob("video.*")
                 if p.suffix.lower() in IMG_EXTS), None)


def download_one(reel):
    sc = reel["shortcode"]
    folder = DATA / sc
    folder.mkdir(parents=True, exist_ok=True)

    opts = {
        "outtmpl": str(folder / "video.%(ext)s"),
        # Paksa mp4 (YouTube dkk. sering webm) agar bisa diputar & di-seek di web.
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        # Thumbnail TikTok berekstensi ".image", YouTube ".webp" -> seragamkan ke jpg.
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg",
                            "when": "before_dl"}],
        "cookiefile": str(COOKIES),
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 3,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(reel["url"], download=True)

    video = _find_video(folder)
    thumb = _find_thumb(folder)
    if not video:
        # Mis. slideshow TikTok lewat URL /video/: yt-dlp hanya dapat audio latar.
        raise NoVideoFile("yt-dlp tidak menghasilkan file video")

    posted = info.get("upload_date")  # YYYYMMDD
    posted = f"{posted[:4]}-{posted[4:6]}-{posted[6:]}" if posted else None

    db.update_reel(
        sc,
        author=info.get("uploader") or info.get("uploader_id"),
        caption=info.get("description"),
        posted_at=posted,
        duration_s=info.get("duration"),
        video_path=str(video) if video else None,
        thumb_path=str(thumb) if thumb else None,
        status="downloaded",
    )
    return info.get("duration")


# --- Fallback: postingan foto / carousel (yt-dlp: "No video formats found") ---

IG_APP_ID = "936619743392459"   # app id web Instagram
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def media_id(shortcode):
    """Shortcode adalah media id dalam base64url."""
    n = 0
    for ch in shortcode:
        n = n * 64 + B64.index(ch)
    return n


def _api_item(shortcode):
    jar = http.cookiejar.MozillaCookieJar(str(COOKIES))
    jar.load(ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"https://www.instagram.com/api/v1/media/{media_id(shortcode)}/info/",
        headers={"User-Agent": UA, "X-IG-App-ID": IG_APP_ID})
    with opener.open(req, timeout=30) as resp:
        body, final_url = resp.read(), resp.geturl()
    # Sesi habis -> Instagram mengalihkan ke halaman login (HTML), bukan JSON.
    if "/accounts/login" in final_url or not body.lstrip().startswith(b"{"):
        raise InstagramLoginRequired(LOGIN_HELP)
    return json.loads(body)["items"][0]


class InstagramLoginRequired(RuntimeError):
    pass


_anon_lock = threading.Lock()


def _anon_item(shortcode):
    """Data postingan Instagram publik TANPA login, atau None.

    yt-dlp sudah mengambil data postingan secara anonim (`xig_polaris_media`), tetapi
    berhenti ("There is no video in this post") bila postingan hanya berisi foto, karena
    ia pengunduh video. Data itu disadap tepat saat diberikan ke `_extract_product`;
    bentuknya sama dengan item API media (carousel_media, image_versions2, caption, user).
    """
    from yt_dlp.extractor.instagram import InstagramIE

    captured = {}
    with _anon_lock:   # tambalan sementara pada kelas -> jangan dipakai bersamaan
        original = InstagramIE._extract_product

        def spy(self, product_info, *args, **kwargs):
            captured.setdefault("item", product_info)   # panggilan pertama = postingan induk
            return original(self, product_info, *args, **kwargs)

        InstagramIE._extract_product = spy
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
                ydl.extract_info(f"https://www.instagram.com/p/{shortcode}/",
                                 download=False, process=False)
        except yt_dlp.utils.DownloadError:
            pass   # "There is no video in this post" dll. — data mungkin sudah tertangkap
        finally:
            InstagramIE._extract_product = original
    item = captured.get("item")
    if isinstance(item, list):
        item = item[0] if item else None
    return item if isinstance(item, dict) and (item.get("carousel_media") or item.get("image_versions2")) else None


LOGIN_HELP = ("Postingan ini tidak bisa dibuka tanpa login (privat/dibatasi) dan sesi "
              "Instagram habis. Klik \"Login Instagram\" di jendela Tambah materi (atau "
              "jalankan: python login.py), login, lalu coba lagi.")


def instagram_logged_in():
    """True bila cookies.txt memuat sessionid (tanda masih login Instagram)."""
    if not COOKIES.exists():
        return False
    jar = http.cookiejar.MozillaCookieJar(str(COOKIES))
    jar.load(ignore_discard=True, ignore_expires=True)
    return any(c.name == "sessionid" and c.value and "instagram.com" in c.domain for c in jar)


def _fetch(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        path.write_bytes(resp.read())


def download_slides(reel, item=None):
    """Unduh semua slide (foto/video) postingan Instagram. `item` = data postingan
    (dari _anon_item tanpa login); bila None diambil lewat API media (butuh login).
    Slide disimpan sebagai data/<sc>/slide_NN.jpg|mp4. Mengembalikan jumlah slide."""
    sc = reel["shortcode"]
    folder = DATA / sc
    folder.mkdir(parents=True, exist_ok=True)

    item = item or _api_item(sc)
    # yt-dlp mungkin sudah sempat mengunduh slide pertama sebagai video.* sebelum gagal.
    for leftover in folder.glob("video.*"):
        leftover.unlink()
    parts = item.get("carousel_media") or [item]
    first_video = first_img = None
    for i, m in enumerate(parts, 1):
        if m.get("media_type") == 2 and m.get("video_versions"):
            path = folder / f"slide_{i:02d}.mp4"
            _fetch(m["video_versions"][0]["url"], path)
            first_video = first_video or path
        else:
            path = folder / f"slide_{i:02d}.jpg"
            _fetch(m["image_versions2"]["candidates"][0]["url"], path)
            first_img = first_img or path

    taken = item.get("taken_at")
    user = item.get("user") or {}
    fields = dict(
        url=f"https://www.instagram.com/p/{sc}/",
        author=user.get("full_name") or user.get("username"),
        caption=(item.get("caption") or {}).get("text"),
        posted_at=time.strftime("%Y-%m-%d", time.localtime(taken)) if taken else None,
        video_path=str(first_video) if first_video else None,
        thumb_path=str(first_img or first_video),
    )
    if first_video:
        fields["status"] = "downloaded"        # video slide -> ditranskrip process.py
    else:
        # Tanpa audio sama sekali: lewati transkrip, isi dibaca lewat OCR (ocr.py).
        fields.update(status="transcribed", transcript="")
    db.update_reel(sc, **fields)
    return len(parts)


def download_reel(reel):
    """Unduh satu item: yt-dlp dulu; untuk postingan foto/carousel Instagram
    (yt-dlp: "No video formats found") ambil slide via API media; slideshow TikTok
    (/photo/) diambil dari halaman TikTok. Mengembalikan catatan singkat untuk log."""
    url = reel["url"] or ""
    if tiktok.is_tiktok(url):
        return _download_tiktok(reel)
    try:
        dur = download_one(reel)
        return f"{dur or '?'} dtk"
    except (yt_dlp.utils.DownloadError, NoVideoFile) as exc:
        if "instagram.com" not in url:
            raise
        # Postingan foto/carousel: coba tanpa login dulu (postingan publik), baru API login.
        item = _anon_item(reel["shortcode"])
        if item:
            return f"carousel {download_slides(reel, item)} slide (tanpa login)"
        if not instagram_logged_in():
            raise InstagramLoginRequired(LOGIN_HELP) from exc
        return f"carousel {download_slides(reel)} slide"


def _download_tiktok(reel, attempts=3):
    """TikTok: slideshow /photo/ diambil dari halaman; video lewat yt-dlp.
    TikTok kadang memblokir sementara (HTTP 403/429) -> coba ulang dengan jeda."""
    if "/photo/" in reel["url"]:
        return f"slideshow {tiktok.download_photo_post(reel)} gambar"
    for attempt in range(1, attempts + 1):
        try:
            dur = download_one(reel)
            return f"{dur or '?'} dtk"
        except NoVideoFile:
            # Slideshow yang dibagikan dengan URL /video/: yt-dlp hanya dapat audio latar.
            return f"slideshow {tiktok.download_photo_post(reel)} gambar"
        except yt_dlp.utils.DownloadError as exc:
            if attempt == attempts or not re.search(r"HTTP Error (403|429)", str(exc)):
                raise
            time.sleep(10 * attempt)


def ensure_cookies(max_age_hours=12, log=print):
    """Pakai cookies.txt yang ada bila masih baru & masih login; ekspor ulang bila
    sudah lama atau sesi tidak ada (mungkin baru login lagi lewat login.py/collect.py).
    Bila ekspor gagal (mis. collect.py sedang membuka profil), tetap pakai yang lama."""
    logged_in = instagram_logged_in()
    # Belum login: postingan publik tetap bisa diunduh tanpa login, jadi jangan buka
    # Chromium tiap kali — cukup periksa ulang paling sering tiap 30 menit.
    age_limit = max_age_hours * 3600 if logged_in else 1800
    if COOKIES.exists() and time.time() - COOKIES.stat().st_mtime < age_limit:
        return
    try:
        export_cookies()
    except Exception as exc:
        if not COOKIES.exists():
            raise RuntimeError(
                "Cookies Instagram belum ada dan gagal diekspor. Tutup collect.py "
                f"lalu coba lagi. ({exc})") from exc
        log(f"Peringatan: gagal menyegarkan cookies, memakai yang lama ({exc})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Jumlah reel yang diunduh (0 = semua)")
    ap.add_argument("--cookies", action="store_true",
                    help="Hanya segarkan cookies.txt lalu keluar")
    args = ap.parse_args()

    db.init_db()
    DATA.mkdir(parents=True, exist_ok=True)

    print("Menyegarkan cookies dari profil browser...")
    try:
        export_cookies()
    except Exception as exc:
        print(f"GAGAL ekspor cookies: {exc}")
        print("Pastikan collect.py / browser lain sudah ditutup, lalu ulangi.")
        return
    if args.cookies:
        return

    pending = db.get_by_status("collected")
    if args.limit:
        pending = pending[: args.limit]
    print(f"Akan mengunduh {len(pending)} reel.\n")

    ok = fail = 0
    for i, reel in enumerate(pending, 1):
        sc = reel["shortcode"]
        try:
            note = download_reel(reel)
            ok += 1
            print(f"[{i}/{len(pending)}] OK  {sc}  ({note})")
        except Exception as exc:
            fail += 1
            lines = (str(exc) or repr(exc)).splitlines()
            msg = lines[0][:120] if lines else repr(exc)
            print(f"[{i}/{len(pending)}] GAGAL {sc}: {msg}")
        if i < len(pending):
            time.sleep(random.uniform(DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX))

    print(f"\nSelesai. Berhasil: {ok}, gagal: {fail}.")
    print("Status DB:", db.count_by_status())


if __name__ == "__main__":
    main()
