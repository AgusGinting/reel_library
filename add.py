"""Tambah link secara manual lalu proses sampai masuk perpustakaan.

    python add.py https://www.instagram.com/reel/XXXXXXXXXXX/
    python add.py <link1> <link2> ...
    python add.py --file links.txt        # satu link per baris (boleh teks bebas)

Mendukung link Instagram (reel, post/carousel) dan video lain yang didukung
yt-dlp (YouTube, TikTok, dll.). Link yang sudah ada di perpustakaan dilewati.
"""

import argparse
import sys

import db
import pipeline
from links import parse_links, resolve


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Tambah link ke perpustakaan.")
    ap.add_argument("links", nargs="*", help="link video/postingan")
    ap.add_argument("--file", help="file teks berisi link")
    args = ap.parse_args()

    text = " ".join(args.links)
    if args.file:
        text += "\n" + open(args.file, encoding="utf-8-sig").read()
    items = parse_links(text)
    if not items:
        print("Tidak ada link yang dikenali. Contoh: python add.py https://www.instagram.com/reel/XXXX/")
        return

    db.init_db()
    added = []
    for item in items:
        try:
            item = resolve(item)
        except ValueError as exc:
            print(f"GAGAL     {item['input']}: {exc}")
            continue
        row = db.get_reel(item["shortcode"])
        if row and row["status"] == "processed":
            print(f"SUDAH ADA {item['shortcode']}: {row['title']}")
            continue
        if not row:
            db.add_collected([{"shortcode": item["shortcode"], "url": item["url"]}])
        added.append(item["shortcode"])
        print(f"DIPROSES  {item['shortcode']}  {item['url']}")

    if not added:
        return
    print()
    pipeline.run(only=added)

    print("\nHasil:")
    for sc in added:
        row = db.get_reel(sc)
        state = "selesai" if row["status"] == "processed" else f"berhenti di '{row['status']}'"
        print(f"  {sc}  {state}  {row['title'] or ''}")


if __name__ == "__main__":
    main()
