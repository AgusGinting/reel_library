"""Teks di layar (OCR) untuk item yang transkripnya kosong (reel musik, foto/carousel).

Otomatis dengan Claude API (butuh ANTHROPIC_API_KEY):
    python ocr.py auto

Manual (dibaca oleh Claude Code, tanpa API key):
    python ocr.py frames              # buat data/<sc>/frames.jpg (kolase 4 frame)
    python ocr.py import hasil.json   # simpan {shortcode: teks} ke kolom screen_text

Kolase 2x2 diambil merata sepanjang video, jadi teks yang berganti tetap
tertangkap dalam satu gambar. Postingan foto/carousel tidak dibuatkan kolase;
slide_NN.jpg-nya dibaca langsung.
"""

import base64
import json
import subprocess
import sys

import db
from config import CLAUDE_MODEL, DATA, has_api_key

MAX_IMAGES = 20       # batas gambar per item yang dikirim ke Claude

OCR_SYSTEM = (
    "Kamu mentranskripsikan teks yang tampil di gambar dari reel/postingan Instagram "
    "untuk indeks pencarian perpustakaan pribadi. Gambar bernomor [1], [2], dst.; "
    "kolase frame berisi 4 potongan video dari awal sampai akhir. Untuk tiap gambar "
    "tulis \"[n] \" lalu semua teks yang terbaca, kata per kata dalam bahasa aslinya. "
    "Pertahankan persis nama tool, URL, kode, dan angka. Tulis watermark/handle yang "
    "berulang hanya sekali. Bila gambar hampir tanpa teks, tambahkan catatan singkat "
    "seperti \"[Visual: diagram arsitektur RAG]\". Jangan meringkas dan jangan mengarang; "
    "teks yang tidak terbaca tulis \"[tidak terbaca]\"."
)

MIN_TRANSCRIPT = 20   # transkrip lebih pendek dari ini dianggap "tanpa ucapan"


def targets():
    conn = db.connect()
    rows = conn.execute(
        "SELECT shortcode, video_path, duration_s FROM reels "
        "WHERE status = 'transcribed' AND length(coalesce(transcript, '')) < ? "
        "AND screen_text IS NULL ORDER BY shortcode",
        (MIN_TRANSCRIPT,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def make_frames(reel):
    out = DATA / reel["shortcode"] / "frames.jpg"
    dur = reel["duration_s"] or 10
    # 4 frame merata -> skala lebar 540 -> kolase 2x2 (1080 px lebar)
    vf = f"fps=4/{dur:.2f},scale=540:-2,tile=2x2"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", reel["video_path"],
         "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out)],
        check=True,
    )
    return out


def cmd_frames():
    items = targets()
    print(f"{len(items)} reel perlu OCR.")
    for r in items:
        if not r["video_path"]:
            # Postingan foto/carousel: slide_NN.jpg dibaca langsung, tanpa kolase.
            print(f"SLIDE {r['shortcode']}  (baca data/{r['shortcode']}/slide_*.jpg)")
            continue
        try:
            print(f"OK    {r['shortcode']}  {make_frames(r)}")
        except Exception as exc:
            print(f"GAGAL {r['shortcode']}: {exc}")


def cmd_import(path):
    results = json.loads(open(path, encoding="utf-8").read())
    for sc, text in results.items():
        db.update_reel(sc, screen_text=text.strip())
    print(f"{len(results)} teks layar disimpan.")


def ocr_images(reel):
    """Gambar yang dibaca: kolase frame (bila ada video) lalu slide foto."""
    images = []
    if reel["video_path"]:
        images.append(make_frames(reel))
    images += sorted((DATA / reel["shortcode"]).glob("slide_*.jpg"))
    return images[:MAX_IMAGES]


def auto_ocr(client, reel):
    """Baca teks layar satu item dengan Claude API dan simpan ke screen_text."""
    images = ocr_images(reel)
    if not images:
        db.update_reel(reel["shortcode"], screen_text="")
        return ""
    content = []
    for i, path in enumerate(images, 1):
        content.append({"type": "text", "text": f"Gambar [{i}]"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.standard_b64encode(path.read_bytes()).decode()}})
    content.append({"type": "text", "text": "Transkripsikan teks pada gambar-gambar di atas."})

    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=OCR_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude menolak membaca gambar item ini")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    db.update_reel(reel["shortcode"], screen_text=text)
    return text


def cmd_auto():
    import anthropic
    items = targets()
    print(f"{len(items)} item perlu OCR.")
    if not items or not has_api_key():
        return
    client = anthropic.Anthropic()
    for r in items:
        try:
            text = auto_ocr(client, r)
            print(f"OK    {r['shortcode']}  {len(text)} char")
        except Exception as exc:
            print(f"GAGAL {r['shortcode']}: {exc}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    if len(sys.argv) >= 2 and sys.argv[1] == "auto":
        cmd_auto()
    elif len(sys.argv) >= 2 and sys.argv[1] == "frames":
        cmd_frames()
    elif len(sys.argv) >= 3 and sys.argv[1] == "import":
        cmd_import(sys.argv[2])
    else:
        print(__doc__)
