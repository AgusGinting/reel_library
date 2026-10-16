"""Dukungan khusus TikTok yang tidak ditangani yt-dlp.

- Link pendek (vm.tiktok.com, vt.tiktok.com, tiktok.com/t/...) dibuka redirect-nya
  untuk mendapatkan URL asli; link yang sudah mati diarahkan TikTok ke beranda.
- Postingan foto/slideshow (/@user/photo/<id>) tidak dikenali yt-dlp. Gambarnya
  diambil dari data halaman (__UNIVERSAL_DATA_FOR_REHYDRATION__) dan disimpan sebagai
  data/<id>/slide_NN.jpg, sama seperti carousel Instagram.
Video TikTok biasa tetap diunduh oleh yt-dlp (download.py).
"""

import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import db
from config import DATA

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "id,en;q=0.9"}

POST_RE = re.compile(r"tiktok\.com/@([^/?#]*)/(video|photo)/(\d+)")
SHORT_RE = re.compile(r"^https?://(?:(?:vm|vt)\.tiktok\.com/|(?:www\.)?tiktok\.com/t/)", re.I)
DATA_RE = re.compile(
    r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)


def is_tiktok(url):
    return "tiktok.com" in (url or "").lower()


def _open(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def canonical(url):
    """Kembalikan (jenis 'video'|'photo', id, url_bersih). Link pendek dibuka dulu."""
    if SHORT_RE.match(url):
        with _open(url) as resp:
            url = resp.geturl()
    m = POST_RE.search(url)
    if not m:
        raise ValueError("Link TikTok tidak berlaku lagi (postingan dihapus/privat) "
                         "atau bukan link video/foto.")
    user, kind, post_id = m.groups()
    return kind, post_id, f"https://www.tiktok.com/@{user}/{kind}/{post_id}"


def _get_html(url, attempts=3):
    # TikTok kadang memblokir sementara (403/429) bila diakses beruntun -> coba ulang.
    for attempt in range(1, attempts + 1):
        try:
            with _open(url) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if attempt == attempts or exc.code not in (403, 429):
                raise
            time.sleep(10 * attempt)


def fetch_item(url):
    """Ambil data postingan (itemStruct) dari halaman TikTok."""
    html = _get_html(url)
    m = DATA_RE.search(html)
    if not m:
        raise RuntimeError("Data halaman TikTok tidak ditemukan (format halaman berubah?)")
    detail = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
    item = detail.get("itemInfo", {}).get("itemStruct")
    if not item:
        status = detail.get("statusMsg") or detail.get("statusCode")
        why = f" (kode {status})" if status not in (None, "", 0) else ""
        raise RuntimeError(f"Postingan TikTok tidak bisa dibuka{why}; mungkin dihapus, "
                           "privat, atau dibatasi wilayah.")
    return item


def _save_jpg(data, path):
    """Simpan gambar sebagai JPEG; format lain (webp/heic/png) dikonversi ffmpeg."""
    if data[:3] == b"\xff\xd8\xff":
        path.write_bytes(data)
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.img"
        src.write_bytes(data)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-q:v", "3", str(path)],
                       check=True)


def download_photo_post(reel):
    """Unduh semua gambar slideshow TikTok + caption. Mengembalikan jumlah slide."""
    item = fetch_item(reel["url"])
    images = (item.get("imagePost") or {}).get("images") or []
    if not images:
        raise RuntimeError("Postingan ini bukan slideshow foto atau gambarnya tidak tersedia.")

    folder = DATA / reel["shortcode"]
    folder.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(images, 1):
        urls = (img.get("imageURL") or {}).get("urlList") or []
        if not urls:
            continue
        with _open(urls[0], timeout=60) as resp:
            _save_jpg(resp.read(), folder / f"slide_{i:02d}.jpg")

    slides = sorted(folder.glob("slide_*.jpg"))
    if not slides:
        raise RuntimeError("Tidak ada gambar yang berhasil diunduh.")
    author = item.get("author") or {}
    created = int(item.get("createTime") or 0)
    db.update_reel(
        reel["shortcode"],
        author=author.get("nickname") or author.get("uniqueId"),
        caption=item.get("desc"),
        posted_at=time.strftime("%Y-%m-%d", time.localtime(created)) if created else None,
        thumb_path=str(slides[0]),
        video_path=None,
        # Slideshow hanya berisi musik latar: lewati transkrip, isi dibaca lewat OCR.
        status="transcribed", transcript="",
    )
    return len(slides)
