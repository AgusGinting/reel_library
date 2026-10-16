"""Tahap 4 (CLI) — Tanya jawab dengan seluruh isi perpustakaan memakai Claude API.

Seluruh perpustakaan (~45 ribu token) dimuat ke system prompt dan di-cache,
jadi pertanyaan berikutnya hanya membayar sebagian kecil biaya input.
Claude menjawab berdasarkan isi perpustakaan dan menyebut reel sumbernya.

Jalankan:
    python ask.py                          # mode tanya jawab interaktif
    python ask.py "reel mana yang bahas RAG?"   # satu pertanyaan
"""

import json
import re
import sys

import anthropic

import db
from config import CLAUDE_MODEL, has_api_key

INSTRUCTIONS = (
    "Kamu adalah asisten belajar untuk perpustakaan pribadi pengguna. Perpustakaan "
    "berisi reel dan postingan Instagram yang pernah dikirim ke DM pengguna; isinya "
    "ada di dalam tag <perpustakaan> di bawah. Jawab pertanyaan pengguna dalam Bahasa "
    "Indonesia berdasarkan isi perpustakaan itu. Setiap kali memakai informasi dari "
    "sebuah item, sebutkan id item itu dalam kurung siku, satu id per kurung, misalnya "
    "[R12] atau [R3][R40]. Pastikan id cocok dengan judul item yang kamu maksud. Kalau "
    "perpustakaan tidak memuat jawabannya, katakan terus terang, lalu boleh tambahkan "
    "pengetahuan umummu dengan label jelas bahwa itu di luar perpustakaan. Transkrip "
    "berasal dari Whisper dan bisa berisi salah dengar."
)


def build_library():
    """Susun teks perpustakaan untuk system prompt.

    Tiap item diberi id pendek R1, R2, ... alih-alih shortcode Instagram: shortcode
    berupa 11 karakter acak yang mudah tertukar oleh model (mis. DcRaD8vsTwR vs
    DcRJg5fDdsJ). Mengembalikan (teks, refs) dengan refs = {"R1": {shortcode, title, url}}.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM reels WHERE status IN ('transcribed', 'processed') "
        "ORDER BY shortcode").fetchall()   # urutan tetap -> cache tidak pecah
    conn.close()
    items, refs = [], {}
    for i, r in enumerate(rows, 1):
        ref = f"R{i}"
        title = r["title"] or (r["caption"] or r["shortcode"]).strip().splitlines()[0][:80]
        refs[ref] = {"shortcode": r["shortcode"], "title": title, "url": r["url"]}
        learn = {1: "ya", 0: "tidak"}.get(r["is_learning"], "belum dinilai")
        head = (f'<item id="{ref}" judul="{r["title"] or ""}" '
                f'kategori="{r["category"] or ""}" materi_belajar="{learn}">')
        body = [f"Pengunggah: {r['author'] or '-'}"]
        for label, key in (("Ringkasan", "summary"), ("Caption", "caption"),
                           ("Transkrip", "transcript"), ("Teks layar", "screen_text")):
            text = (r[key] or "").strip()
            if text:
                body.append(f"{label}: {text}")
        items.append(head + "\n" + "\n".join(body) + "\n</item>")
    return "<perpustakaan>\n" + "\n\n".join(items) + "\n</perpustakaan>", refs


class Librarian:
    def __init__(self):
        self.client = anthropic.Anthropic()
        library, self.refs = build_library()
        self.system = [
            {"type": "text", "text": INSTRUCTIONS},
            {"type": "text", "text": library, "cache_control": {"type": "ephemeral"}},
        ]
        self.messages = []
        self.count = len(self.refs)

    def stream(self, question):
        """Alirkan potongan teks jawaban (rujukan berupa [R12]). Setelah selesai,
        self.cited berisi id R yang dirujuk (urut kemunculan, hanya yang valid) dan
        self.usage berisi pemakaian token. Dipakai CLI & web."""
        self.messages.append({"role": "user", "content": question})
        try:
            with self.client.beta.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium"},
                system=self.system,
                messages=self.messages,
            ) as stream:
                yield from stream.text_stream
                response = stream.get_final_message()
        except BaseException:
            self.messages.pop()   # pertanyaan gagal tidak masuk riwayat
            raise
        # Simpan seluruh blok (termasuk thinking) agar percakapan bisa berlanjut.
        self.messages.append({"role": "assistant", "content": response.content})

        answer = "".join(b.text for b in response.content if b.type == "text")
        self.cited = [ref for ref in dict.fromkeys(re.findall(r"\[(R\d+)\]", answer))
                      if ref in self.refs]
        self.usage = response.usage

    def ask(self, question):
        for text in self.stream(question):
            print(text, end="", flush=True)
        print()
        if self.cited:
            print("\nSumber:")
            for ref in self.cited:
                r = self.refs[ref]
                print(f"  [{ref}] {r['title']} - {r['url']}")
        u = self.usage
        print(f"\n(token input {u.input_tokens:,}, ditulis ke cache {u.cache_creation_input_tokens or 0:,}, "
              f"dibaca dari cache {u.cache_read_input_tokens or 0:,}, output {u.output_tokens:,})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_db()
    if not has_api_key():
        return
    lib = Librarian()
    print(f"Perpustakaan dimuat: {lib.count} item. Model: {CLAUDE_MODEL}.")

    if len(sys.argv) > 1:
        lib.ask(" ".join(sys.argv[1:]))
        return

    print("Ketik pertanyaan (kosong / 'keluar' untuk berhenti).\n")
    while True:
        try:
            q = input("Kamu> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in {"keluar", "exit", "quit"}:
            break
        print("\nAI> ", end="")
        try:
            lib.ask(q)
        except anthropic.AuthenticationError:
            print("API key tidak valid. Periksa isi file .env.")
            return
        except anthropic.APIError as exc:
            print(f"\nGagal: {exc}")
        print()


if __name__ == "__main__":
    main()
