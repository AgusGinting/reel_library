"""Tahap 3b — Ringkas, beri tag & kategori tiap reel dengan Claude API.

Untuk tiap item status='transcribed': kirim caption + transkrip + teks layar ke
Claude, simpan judul, ringkasan (+ poin penting), topik, kategori, dan penanda
apakah ini materi belajar. Status naik ke 'processed'.

Butuh ANTHROPIC_API_KEY (env atau file .env di folder proyek).

Jalankan:
    python summarize.py            # proses semua yang belum
    python summarize.py --limit 3  # uji beberapa dulu
"""

import argparse
import json
import sys

import anthropic

import db
from config import CLAUDE_MODEL, has_api_key

CATEGORIES = [
    "AI & LLM",
    "Pemrograman & Data",
    "Riset & Akademik",
    "Karier & Produktivitas",
    "Tools & Website",
    "Tips & Lifestyle",
    "Berita & Sosial",
    "Hiburan & Meme",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string",
                  "description": "Judul singkat & spesifik, maks 10 kata, Bahasa Indonesia"},
        "summary": {"type": "string",
                    "description": "Ringkasan 2-4 kalimat dalam Bahasa Indonesia"},
        "key_points": {"type": "array", "items": {"type": "string"},
                       "description": "0-6 poin penting yang bisa dipraktikkan; "
                                      "sertakan nama tool/URL/angka persis bila ada"},
        "topics": {"type": "array", "items": {"type": "string"},
                   "description": "3-6 tag topik, huruf kecil"},
        "category": {"type": "string", "enum": CATEGORIES},
        "is_learning": {"type": "boolean",
                        "description": "true bila berisi pengetahuan/skill yang bisa dipelajari; "
                                       "false untuk meme, hiburan, gosip, berita viral"},
    },
    "required": ["title", "summary", "key_points", "topics", "category", "is_learning"],
    "additionalProperties": False,
}

SYSTEM = (
    "Kamu adalah pustakawan untuk perpustakaan pribadi berisi reel dan postingan "
    "Instagram yang dikirim pengguna lewat DM. Tugasmu mengkatalogkan satu item: "
    "beri judul, ringkasan, poin penting, tag topik, kategori, dan tentukan apakah "
    "item ini materi belajar. Bahan yang tersedia: caption, transkrip audio (bisa "
    "kosong atau berisi salah dengar dari Whisper), dan teks di layar hasil OCR. "
    "Tulis dalam Bahasa Indonesia, tetapi istilah teknis, nama tool, dan URL tetap "
    "apa adanya. Jangan mengarang informasi yang tidak ada di bahan."
)


def build_prompt(reel):
    parts = [f"Pengunggah: {reel['author'] or '-'}"]
    for label, key in (("Caption", "caption"), ("Transkrip audio", "transcript"),
                       ("Teks di layar (OCR)", "screen_text")):
        text = (reel[key] or "").strip()
        parts.append(f"<{label}>\n{text or '(kosong)'}\n</{label}>")
    return "\n\n".join(parts)


def catalog(client, reel):
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(reel)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude menolak memproses item ini")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.usage


def save(reel, data):
    summary = data["summary"].strip()
    if data["key_points"]:
        summary += "\n\nPoin penting:\n" + "\n".join(f"- {p}" for p in data["key_points"])
    db.update_reel(
        reel["shortcode"],
        title=data["title"].strip(),
        summary=summary,
        topics=json.dumps(data["topics"], ensure_ascii=False),
        category=data["category"],
        is_learning=int(data["is_learning"]),
        status="processed",
    )


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db.init_db()
    pending = db.get_by_status("transcribed")
    if args.limit:
        pending = pending[: args.limit]
    if not pending:
        print("Tidak ada item berstatus 'transcribed'.")
        return

    if not has_api_key():
        return
    client = anthropic.Anthropic()

    print(f"Mengkatalogkan {len(pending)} item dengan {CLAUDE_MODEL}...\n")
    ok = fail = tok_in = tok_out = 0
    for i, reel in enumerate(pending, 1):
        sc = reel["shortcode"]
        try:
            data, usage = catalog(client, reel)
            save(reel, data)
            tok_in += usage.input_tokens
            tok_out += usage.output_tokens
            ok += 1
            mark = "BELAJAR" if data["is_learning"] else "lainnya"
            print(f"[{i}/{len(pending)}] {sc}  [{mark}] {data['category']} | {data['title']}")
        except anthropic.AuthenticationError:
            print("API key tidak valid. Periksa isi file .env.")
            return
        except (anthropic.APIError, RuntimeError, ValueError) as exc:
            fail += 1
            print(f"[{i}/{len(pending)}] GAGAL {sc}: {exc}")

    # Harga Claude Opus 5.5: $4 / 1 juta token input, $20 / 1 juta token output.
    cost = tok_in * 4 / 1e6 + tok_out * 20 / 1e6
    print(f"\nSelesai. Berhasil: {ok}, gagal: {fail}.")
    print(f"Token: {tok_in:,} input + {tok_out:,} output, perkiraan biaya ${cost:.2f}")
    print("Status DB:", db.count_by_status())


if __name__ == "__main__":
    main()
