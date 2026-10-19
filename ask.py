"""Tahap 4 (CLI) — Tanya jawab dengan seluruh isi perpustakaan memakai Claude API.

Seluruh perpustakaan (~45 ribu token) dimuat ke system prompt dan di-cache,
jadi pertanyaan berikutnya hanya membayar sebagian kecil biaya input.
Claude menjawab berdasarkan isi perpustakaan dan menyebut reel sumbernya.

Jalankan:
    python ask.py                          # mode tanya jawab interaktif
    python ask.py "reel mana yang bahas RAG?"   # satu pertanyaan
    python ask.py --model claude-haiku-4-5 "..."   # pilih model Claude dari CHAT_MODELS
    python ask.py --web "berita terbaru soal ..."  # izinkan akses internet (web_tools.py)
"""

import json
import re
import sys
from types import SimpleNamespace

import anthropic

import db
import web_tools
from config import CHAT_MODELS, CLAUDE_MODEL, has_api_key

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


def numbered_items(refs=None):
    """Semua item yang bisa ditanyakan, masing-masing dengan id pendek R1, R2, ...

    Id pendek dipakai alih-alih shortcode Instagram: shortcode berupa 11 karakter acak
    yang mudah tertukar oleh model (mis. DcRaD8vsTwR vs DcRJg5fDdsJ).
    `refs` lama (dari percakapan tersimpan) mempertahankan nomor yang sama untuk item
    yang sama, supaya rujukan di jawaban lama tetap benar; item baru diberi nomor lanjutan.
    Mengembalikan (list (ref, row) urut nomor, refs {"R1": {shortcode, title, url}}).
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM reels WHERE status IN ('transcribed', 'processed') "
        "ORDER BY shortcode").fetchall()   # urutan tetap -> cache tidak pecah
    conn.close()

    known = {v["shortcode"]: k for k, v in (refs or {}).items()}
    next_n = max((int(k[1:]) for k in known.values()), default=0) + 1
    numbered = []
    for r in rows:
        ref = known.get(r["shortcode"])
        if ref is None:
            ref, next_n = f"R{next_n}", next_n + 1
        numbered.append((int(ref[1:]), ref, r))
    numbered.sort(key=lambda x: x[0])

    items = [(ref, r) for _, ref, r in numbered]
    refs = {ref: {"shortcode": r["shortcode"], "title": item_title(r), "url": r["url"]}
            for ref, r in items}
    return items, refs


def item_title(r):
    return r["title"] or (r["caption"] or r["shortcode"]).strip().splitlines()[0][:80]


def format_item(ref, r, limit=None):
    """Satu item sebagai blok <item>. `limit` memangkas tiap bagian teks panjang."""
    learn = {1: "ya", 0: "tidak"}.get(r["is_learning"], "belum dinilai")
    head = (f'<item id="{ref}" judul="{r["title"] or ""}" '
            f'kategori="{r["category"] or ""}" materi_belajar="{learn}">')
    body = [f"Pengunggah: {r['author'] or '-'}"]
    for label, key in (("Ringkasan", "summary"), ("Caption", "caption"),
                       ("Transkrip", "transcript"), ("Teks layar", "screen_text")):
        text = (r[key] or "").strip()
        if limit and key != "summary" and len(text) > limit:
            text = text[:limit] + "…"
        if text:
            body.append(f"{label}: {text}")
    return head + "\n" + "\n".join(body) + "\n</item>"


def build_library(refs=None):
    """Seluruh perpustakaan sebagai teks untuk system prompt (dipakai Claude).
    Mengembalikan (teks, refs)."""
    items, refs = numbered_items(refs)
    text = "\n\n".join(format_item(ref, r) for ref, r in items)
    return "<perpustakaan>\n" + text + "\n</perpustakaan>", refs


class Librarian:
    """Tanya jawab dengan Claude: seluruh perpustakaan dimuat ke system prompt."""
    model_id = "claude"

    def __init__(self, refs=None, history=None, model=CLAUDE_MODEL, model_id="claude",
                 mode="full", effort="medium", fallbacks=True):
        """refs & history (list {role, text}) dipakai untuk melanjutkan percakapan
        tersimpan. Riwayat dikirim sebagai teks saja: blok thinking terikat pada system
        prompt aslinya, yang bisa berubah bila perpustakaan bertambah.

        mode "full"  : seluruh perpustakaan di system prompt (Opus/Sonnet/Fable, konteks 1M).
        mode "search": katalog + detail item relevan per pertanyaan (Haiku, konteks 200K).
        effort None  : jangan kirim output_config.effort (Haiku 4.5 menolaknya).
        fallbacks    : coba model lain otomatis bila model menolak (Opus/Sonnet/Fable).
        """
        self.client = anthropic.Anthropic()
        self.model, self.model_id, self.effort, self.fallbacks = model, model_id, effort, fallbacks
        self.retriever = None
        if mode == "search":
            from retrieval import Retriever   # impor di sini: retrieval memakai modul ini
            self.retriever = Retriever(refs)
            self.refs = self.retriever.refs
            self.system = [{"type": "text", "text": self.retriever.system_prompt()}]
        else:
            library, self.refs = build_library(refs)
            self.system = [{"type": "text", "text": INSTRUCTIONS},
                           {"type": "text", "text": library}]
        # Petunjuk alat internet selalu ada & tidak berubah antar pertanyaan: system prompt
        # dan daftar alat yang berubah di tengah percakapan membatalkan blok thinking (400).
        self.system.append({"type": "text", "text": web_tools.INSTRUCTIONS,
                            "cache_control": {"type": "ephemeral"}})
        self.messages = [{"role": m["role"], "content": m["text"]} for m in history or []]
        self.questions = [m["text"] for m in history or [] if m["role"] == "user"]
        self.count = len(self.refs)

    def stream(self, question, web=False):
        """Alirkan jawaban: str = potongan teks (rujukan berupa [R12]); dict {"tool": ...}
        = model sedang memakai alat internet (hanya bila web=True). Setelah selesai:
        self.answer teks jawaban utuh, self.cited id R yang dirujuk, self.web daftar
        pencarian/halaman yang dipakai, self.usage total token. Dipakai CLI & web."""
        content = question
        if self.retriever:
            content = self.retriever.user_message(question, self.questions)
        if web:
            content = f"{web_tools.TURN_NOTE}\n\n{content}"   # pesan baru: aman untuk cache & thinking
        start = len(self.messages)
        self.messages.append({"role": "user", "content": content})

        params = dict(model=self.model, max_tokens=16000, system=self.system,
                      tools=web_tools.claude_tools())
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        api = self.client.beta.messages if self.fallbacks else self.client.messages

        self.web, texts = [], []
        totals = dict.fromkeys(("input_tokens", "output_tokens", "cache_read_input_tokens",
                                "cache_creation_input_tokens"), 0)
        try:
            for round_no in range(web_tools.MAX_ROUNDS + 1):
                # Internet mati / batas putaran habis -> alat tetap terdaftar tapi tidak
                # boleh dipakai (tool_choice boleh berubah tanpa membatalkan thinking).
                allow = web and round_no < web_tools.MAX_ROUNDS
                params["tool_choice"] = {"type": "auto"} if allow else {"type": "none"}
                first = True
                with api.stream(**params, messages=self.messages) as stream:
                    for text in stream.text_stream:
                        if first and texts:
                            yield "\n\n"   # pisahkan teks dari putaran sebelumnya
                        first = False
                        yield text
                    response = stream.get_final_message()
                # Simpan seluruh blok (termasuk thinking & tool_use) agar percakapan bisa berlanjut.
                self.messages.append({"role": "assistant", "content": response.content})
                for key in totals:
                    totals[key] += getattr(response.usage, key, 0) or 0
                texts += [b.text for b in response.content if b.type == "text"]

                if response.stop_reason == "refusal":
                    raise RuntimeError("Claude menolak menjawab pertanyaan ini.")
                calls = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not calls:
                    break
                results = []
                for call in calls:
                    info = web_tools.describe(call.name, call.input)
                    self.web.append(info)
                    yield {"tool": info}
                    output = (web_tools.run_tool(call.name, call.input) if allow
                              else "ERROR: akses internet dimatikan oleh pengguna.")
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": output})
                self.messages.append({"role": "user", "content": results})
        except BaseException:
            del self.messages[start:]   # pertanyaan gagal tidak masuk riwayat
            raise

        self.questions.append(question)
        self.answer = "\n\n".join(t for t in texts if t.strip())
        self.cited = [ref for ref in dict.fromkeys(re.findall(r"\[(R\d+)\]", self.answer))
                      if ref in self.refs]
        self.usage = SimpleNamespace(**totals)

    def ask(self, question, web=False):
        for chunk in self.stream(question, web=web):
            if isinstance(chunk, dict):
                t = chunk["tool"]
                print(f"\n[{'cari' if t['type'] == 'search' else 'buka'}: {t['label']}]", flush=True)
            else:
                print(chunk, end="", flush=True)
        print()
        if self.cited:
            print("\nSumber:")
            for ref in self.cited:
                r = self.refs[ref]
                print(f"  [{ref}] {r['title']} - {r['url']}")
        u = self.usage
        print(f"\n(token input {u.input_tokens:,}, ditulis ke cache {u.cache_creation_input_tokens or 0:,}, "
              f"dibaca dari cache {u.cache_read_input_tokens or 0:,}, output {u.output_tokens:,})")


def claude_librarian(model_id, refs=None, history=None):
    """Librarian untuk model Claude dari CHAT_MODELS (config.py)."""
    m = next(m for m in CHAT_MODELS if m["id"] == model_id and m["provider"] == "anthropic")
    return Librarian(refs=refs, history=history, model=m["model"], model_id=m["id"],
                     mode=m.get("mode", "full"), effort=m.get("effort", "medium"),
                     fallbacks=m.get("fallbacks", True))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    model_id = "claude"
    web = "--web" in args          # izinkan akses internet (web_tools.py)
    args = [a for a in args if a != "--web"]
    if len(args) >= 2 and args[0] == "--model":
        model_id, args = args[1], args[2:]
    claude_ids = [m["id"] for m in CHAT_MODELS if m["provider"] == "anthropic"]
    if model_id not in claude_ids:
        print(f"Model tidak dikenal: {model_id}. Pilihan: {', '.join(claude_ids)}")
        return
    db.init_db()
    if not has_api_key():
        return
    lib = claude_librarian(model_id)
    print(f"Perpustakaan dimuat: {lib.count} item. Model: {lib.model}.")

    if args:
        lib.ask(" ".join(args), web=web)
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
            lib.ask(q, web=web)
        except anthropic.AuthenticationError:
            print("API key tidak valid. Periksa isi file .env.")
            return
        except anthropic.APIError as exc:
            print(f"\nGagal: {exc}")
        print()


if __name__ == "__main__":
    main()
