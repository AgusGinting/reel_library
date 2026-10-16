"""Mengenali link yang ditambahkan manual (CLI add.py & tombol "Tambah" di web).

Link Instagram (reel, post, tv) langsung dikenali shortcode-nya. Link lain
(YouTube, TikTok, dll. yang didukung yt-dlp) diperiksa yt-dlp untuk mendapatkan id.
"""

import re

SC_RE = re.compile(r"^[A-Za-z0-9_-]{9,}$")   # id item yang valid (juga dipakai library.py)
URL_RE = re.compile(r"https?://[^\s<>\"']+")
IG_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(reels?|p|tv)/([A-Za-z0-9_-]+)", re.I)


def parse_links(text):
    """Ambil semua URL dari teks bebas (satu atau banyak, dipisah spasi/baris).
    Mengembalikan list dict {input, shortcode, url}; shortcode None untuk link
    non-Instagram (diisi oleh resolve())."""
    items, seen = [], set()
    for raw in URL_RE.findall(text or ""):
        raw = raw.rstrip(").,;")
        m = IG_RE.search(raw)
        if m:
            kind, code = m.groups()
            path = "p" if kind.lower() == "p" else "reel"
            item = {"input": raw, "shortcode": code,
                    "url": f"https://www.instagram.com/{path}/{code}/"}
        else:
            item = {"input": raw, "shortcode": None, "url": raw}
        key = item["shortcode"] or item["url"]
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items


def resolve(item):
    """Lengkapi shortcode & url untuk link non-Instagram lewat yt-dlp (tanpa mengunduh)."""
    if item["shortcode"]:
        return item
    import tiktok
    if tiktok.is_tiktok(item["url"]):
        # Ditangani sendiri: link pendek, link mati, dan slideshow /photo/ (tak didukung yt-dlp).
        try:
            _, post_id, url = tiktok.canonical(item["url"])
        except OSError as exc:
            raise ValueError(f"Link TikTok tidak bisa dibuka: {exc}") from exc
        return {**item, "shortcode": post_id, "url": url}
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(item["url"], download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ValueError(f"Link tidak bisa dibaca: {str(exc).splitlines()[0][:150]}") from exc
    if info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Link playlist belum didukung; tempel link video satuan.")
    vid = str(info.get("id") or "")
    if not SC_RE.match(vid):
        prefix = (info.get("extractor_key") or "web").lower()
        vid = re.sub(r"[^A-Za-z0-9_-]", "-", f"{prefix}-{vid}")
    return {**item, "shortcode": vid, "url": info.get("webpage_url") or item["url"]}
