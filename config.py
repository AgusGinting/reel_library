"""Konfigurasi terpusat untuk semua tahap pipeline."""

from pathlib import Path

BASE = Path(__file__).resolve().parent

PROFILE = BASE / "browser_profile"   # sesi login Instagram (Playwright)
DATA = BASE / "data"                 # <shortcode>/video.mp4, dst
DB_PATH = BASE / "library.db"        # SQLite perpustakaan
CSV_OUT = BASE / "captured_reels.csv"

# Tahap 3 (transkrip lokal)
WHISPER_MODEL = "small"              # tiny|base|small|medium — RTX 3050 4GB nyaman di small
WHISPER_DEVICE = "cuda"             # "cuda" (GPU) atau "cpu"
WHISPER_COMPUTE = "int8_float16"    # hemat VRAM

# Tahap 3b/4 (Claude API). Key dibaca dari env atau file .env (jangan ditulis di kode).
CLAUDE_MODEL = "claude-opus-5-5"


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
        print("API key Claude belum diatur. Buat file .env di folder proyek berisi:\n"
          "    ANTHROPIC_API_KEY=sk-ant-...\n"
          f"(lokasi: {BASE / '.env'})")
    return False

# Jeda unduhan tahap 2 (detik, acak dalam rentang) agar tidak diblokir
DOWNLOAD_DELAY_MIN = 3
DOWNLOAD_DELAY_MAX = 8
