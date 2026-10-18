"""Konfigurasi terpusat untuk semua tahap pipeline."""

from pathlib import Path

BASE = Path(__file__).resolve().parent

PROFILE = BASE / "browser_profile"  # sesi login Instagram (Playwright)
DATA = BASE / "data"  # <shortcode>/video.mp4, dst
DB_PATH = BASE / "library.db"  # SQLite perpustakaan
CSV_OUT = BASE / "captured_reels.csv"

# Tahap 3 (transkrip lokal)
WHISPER_MODEL = "small"  # tiny|base|small|medium — RTX 3050 4GB nyaman di small
WHISPER_DEVICE = "cuda"  # "cuda" (GPU) atau "cpu"
WHISPER_COMPUTE = "int8_float16"  # hemat VRAM

# Tahap 3b/4 (Claude API). Key dibaca dari env atau file .env (jangan ditulis di kode).
CLAUDE_MODEL = "claude-sonnet-5-5"

# Model yang bisa dipilih di panel "Tanya AI". Tambahkan model Ollama lain di sini
# (nama persis seperti di `ollama list`; model cloud cukup di-`ollama pull` dulu).
#   provider "anthropic": mode "full" (bawaan) = seluruh perpustakaan dimuat ke prompt
#                         (di-cache); mode "search" = katalog + detail item relevan, untuk
#                         model berkonteks kecil. effort None = jangan kirim effort (Haiku
#                         4.5 menolaknya). fallbacks = coba model lain bila model menolak.
#   provider "ollama"   : selalu mode pencarian (hemat jatah gratis).
# Perkiraan biaya untuk ±250 ribu token perpustakaan (224 item, Okt 2026): pertanyaan
# pertama menulis cache, pertanyaan berikutnya dalam 5 menit membaca cache.
OLLAMA_URL = "http://127.0.0.1:11434"
CHAT_MODELS = [
    {
        "id": "claude",  # id lama dipertahankan agar riwayat & pilihan tersimpan tetap cocok
        "provider": "anthropic",
        "model": CLAUDE_MODEL,
        "label": "Claude Sonnet 5.5",
        "note": "±$0,63 pertanyaan pertama, ±$0,03 berikutnya · seluruh perpustakaan",
    },
    {
        "id": "claude-haiku-4-5",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "label": "Claude Haiku 4.5",
        "mode": "search",  # konteks 200K: perpustakaan (±182K token Haiku) hampir penuh
        "effort": None,
        "fallbacks": False,
        "note": "±$0,02 per pertanyaan · tercepat & termurah · mode pencarian",
    },
    {
        "id": "claude-haiku-5-5",
        "provider": "anthropic",
        "model": "claude-haiku-5-5",
        "label": "Claude Haiku 5.5",
        # Konteks 1M & mendukung effort/fallbacks -> mode penuh dengan pengaturan bawaan.
        # Harga Haiku 5.5 naik untuk prompt > 100K token (perpustakaan ±250K):
        # tulis cache $0,625/MTok, baca cache $0,05/MTok, output $2,50/MTok.
        "note": "±$0,16 pertanyaan pertama, ±$0,015 berikutnya · seluruh perpustakaan",
    },
    {
        "id": "claude-opus-5-5",
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "label": "Claude Opus 5.5",
        "note": "±$1,25 pertanyaan pertama, ±$0,05 berikutnya · seluruh perpustakaan",
    },
    {
        "id": "claude-fable-5-1",
        "provider": "anthropic",
        "model": "claude-fable-5-1",
        "label": "Claude Fable 5.1",
        "note": "±$3,10 pertanyaan pertama, ±$0,06 berikutnya · paling cerdas",
    },
    {
        "id": "gemma4:31b-cloud",
        "provider": "ollama",
        "model": "gemma4:31b-cloud",
        "label": "Gemma 4 31B",
        "note": "Gratis · Ollama cloud",
    },
    {
        "id": "treyleo16/kimi-k3",
        "provider": "ollama",
        "model": "treyleo16/kimi-k3",
        "label": "treyleo16/kimi-k3",
        "note": "Gratis · Ollama cloud · isinya Gemma 4 31B, bukan Kimi K3 asli",
    },
]
DEFAULT_CHAT_MODEL = "claude"


def _load_dotenv(path=BASE / ".env"):
    import os

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def has_api_key(quiet=False):
    """True bila ada kredensial Claude; kalau tidak, cetak petunjuk (kecuali quiet)."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    if not quiet:
        print(
            "API key Claude belum diatur. Buat file .env di folder proyek berisi:\n"
            "    ANTHROPIC_API_KEY=sk-ant-...\n"
            f"(lokasi: {BASE / '.env'})"
        )
    return False


# Jeda unduhan tahap 2 (detik, acak dalam rentang) agar tidak diblokir
DOWNLOAD_DELAY_MIN = 3
DOWNLOAD_DELAY_MAX = 8
