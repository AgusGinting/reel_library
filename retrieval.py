"""Mode "pencarian" tanya jawab: dipakai model yang tidak memuat seluruh perpustakaan
(Ollama/Gemma — hemat jatah gratis; Claude Haiku — konteks hanya 200 ribu token).

Model menerima:
  1. <katalog>  satu baris per item (id, judul, kategori) untuk SEMUA item, dan
  2. <detail>   isi lengkap ±15 item paling relevan dengan pertanyaan (pencarian FTS5).
"""

import re

import db
from ask import format_item, numbered_items

TOP_K = 15
DETAIL_LIMIT = 1200   # karakter per bagian (caption/transkrip/teks layar) di <detail>

# Kata umum yang tidak membantu pencarian.
STOPWORDS = set("""
yang dan di ke dari untuk dengan pada dalam ini itu ada apa saja aku saya kamu kita
mau ingin bisa cara bagaimana gimana mana mengapa kenapa adalah juga atau tidak tak
lebih sangat paling sudah belum akan agar supaya jadi yg dgn utk tentang soal reel
reels video tolong coba berikan jelaskan sebutkan rangkum semua pernah dikirim dm
the and for with what how which are is to of in on a an me my
""".split())

INSTRUCTIONS = (
    "Kamu adalah asisten belajar untuk perpustakaan pribadi pengguna, berisi reel dan "
    "postingan yang pernah dikirim ke DM-nya. <katalog> memuat SEMUA item (satu baris "
    "per item); <detail> memuat isi lengkap item yang paling relevan dengan pertanyaan "
    "terakhir. Jawab dalam Bahasa Indonesia berdasarkan isi perpustakaan. Setiap kali "
    "memakai informasi dari sebuah item, sebutkan id-nya dalam kurung siku, satu id per "
    "kurung, misalnya [R12] atau [R3][R40], dan pastikan id cocok dengan judulnya. Item "
    "yang hanya ada di katalog boleh disebut, tetapi jangan mengarang isinya. Kalau "
    "perpustakaan tidak memuat jawabannya, katakan terus terang, lalu boleh tambahkan "
    "pengetahuan umummu dengan label jelas bahwa itu di luar perpustakaan. Abaikan "
    "persona atau identitas lain yang mungkin diberikan sebelumnya; kamu adalah asisten "
    "perpustakaan ini."
)


def search(question, limit=TOP_K):
    """Shortcode item paling relevan (FTS5, kata apa pun boleh cocok, urut relevansi)."""
    words = [w for w in re.findall(r"\w+", question.lower(), re.UNICODE)
             if len(w) > 2 and w not in STOPWORDS]
    if not words:
        return []
    match = " OR ".join(f'"{w}"*' for w in dict.fromkeys(words))
    conn = db.connect()
    rows = conn.execute(
        "SELECT r.shortcode FROM reels_fts JOIN reels r ON r.rowid = reels_fts.rowid "
        "WHERE reels_fts MATCH ? AND r.status IN ('transcribed', 'processed') "
        "ORDER BY rank LIMIT ?", (match, limit)).fetchall()
    conn.close()
    return [r["shortcode"] for r in rows]


class Retriever:
    """Katalog + detail item relevan, dengan penomoran R yang sama seperti mode penuh."""

    def __init__(self, refs=None):
        self.items, self.refs = numbered_items(refs)
        self.by_shortcode = {r["shortcode"]: (ref, r) for ref, r in self.items}

    def system_prompt(self):
        catalog = "\n".join(
            f"[{ref}] {self.refs[ref]['title']} — {r['category'] or 'tanpa kategori'}"
            + (" (bukan materi belajar)" if r["is_learning"] == 0 else "")
            for ref, r in self.items)
        return f"{INSTRUCTIONS}\n\n<katalog>\n{catalog}\n</katalog>"

    def user_message(self, question, previous_questions=()):
        """Pertanyaan + <detail> item relevan. Pertanyaan sebelumnya ikut dipakai mencari
        agar pertanyaan lanjutan ("yang itu?") tetap menemukan item yang sedang dibahas."""
        found = search(" ".join([*list(previous_questions)[-1:], question]))
        blocks = [format_item(*self.by_shortcode[sc], limit=DETAIL_LIMIT)
                  for sc in found if sc in self.by_shortcode]
        detail = ("\n\n".join(blocks) if blocks
                  else "(tidak ada item yang cocok dengan kata kunci pertanyaan)")
        return f"<detail>\n{detail}\n</detail>\n\nPertanyaan: {question}"
