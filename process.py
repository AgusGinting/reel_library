"""Tahap 3 — Transkrip audio tiap reel (faster-whisper, lokal).

Untuk tiap reel status='downloaded': transkrip video -> teks, simpan ke DB
(kolom transcript) + data/<shortcode>/transcript.txt, lalu status='transcribed'.

Ringkasan/tag via LLM (Claude atau Ollama) BELUM diputuskan -> lihat summarize.py
nanti; pipeline transkrip ini sudah bisa jalan sendiri.

Jalankan:
    python process.py            # transkrip semua yang belum
    python process.py --limit 3  # uji beberapa
    python process.py --model medium --device cpu
"""

import argparse
import importlib.util
import os
import sys

import db
from config import DATA, WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE

# Hasil transkrip bisa mengandung karakter non-latin; pastikan konsol UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def enable_cuda_dlls():
    """Tambahkan semua folder nvidia/*/bin (cublas, cudnn, cuda_runtime, nvrtc)
    ke pencarian DLL Windows. cublas butuh cudart, jadi SEMUA harus ditemukan."""
    import glob
    spec = importlib.util.find_spec("nvidia")
    if not spec or not spec.submodule_search_locations:
        return
    bins = []
    for root in spec.submodule_search_locations:
        bins += [b for b in glob.glob(os.path.join(root, "*", "bin"))
                 if os.path.isdir(b)]
    if not bins:
        return
    # PATH perlu di-set juga: add_dll_directory saja tak cukup untuk
    # dependensi berantai (cublas -> cudart) di Windows.
    os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
    for b in bins:
        try:
            os.add_dll_directory(b)
        except Exception:
            pass


def load_model(model_name, device, compute):
    from faster_whisper import WhisperModel
    try:
        m = WhisperModel(model_name, device=device, compute_type=compute)
        print(f"Model '{model_name}' dimuat di {device} ({compute}).")
        return m
    except Exception as exc:
        print(f"Gagal muat di {device}: {str(exc).splitlines()[0][:120]}")
        if device != "cpu":
            print("Fallback ke CPU (int8)...")
            m = WhisperModel(model_name, device="cpu", compute_type="int8")
            print(f"Model '{model_name}' dimuat di cpu (int8).")
            return m
        raise


def has_audio(video_path):
    import av
    with av.open(video_path) as container:
        return len(container.streams.audio) > 0


def transcribe_one(model, video_path):
    # Reel tanpa trek audio (bisu) membuat PyAV melempar IndexError.
    if not has_audio(video_path):
        return "", "no-audio"
    segments, info = model.transcribe(video_path, beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, info.language


def transcribe_reel(model, reel):
    """Transkrip satu item, simpan ke DB (status -> transcribed). Mengembalikan
    (teks, bahasa). Melempar FileNotFoundError bila videonya tidak ada."""
    sc, vp = reel["shortcode"], reel["video_path"]
    if not vp or not os.path.exists(vp):
        raise FileNotFoundError("video tidak ada")
    text, lang = transcribe_one(model, vp)
    db.update_reel(sc, transcript=text, status="transcribed")
    try:
        (DATA / sc / "transcript.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    return text, lang


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=WHISPER_MODEL)
    ap.add_argument("--device", default=WHISPER_DEVICE)
    ap.add_argument("--compute", default=WHISPER_COMPUTE)
    args = ap.parse_args()

    enable_cuda_dlls()
    db.init_db()

    pending = db.get_by_status("downloaded")
    if args.limit:
        pending = pending[: args.limit]
    if not pending:
        print("Tidak ada reel berstatus 'downloaded'. Jalankan download.py dulu.")
        return

    model = load_model(args.model, args.device, args.compute)
    print(f"Akan mentranskrip {len(pending)} reel.\n")

    ok = fail = 0
    for i, reel in enumerate(pending, 1):
        sc = reel["shortcode"]
        try:
            text, lang = transcribe_reel(model, reel)
            ok += 1
            print(f"[{i}/{len(pending)}] OK  {sc}  lang={lang}  {len(text)} char")
        except Exception as exc:
            fail += 1
            msg = (str(exc) or repr(exc)).splitlines()
            msg = msg[0][:120] if msg else repr(exc)
            print(f"[{i}/{len(pending)}] GAGAL {sc}: {msg}")

    print(f"\nSelesai. Berhasil: {ok}, gagal: {fail}.")
    print("Status DB:", db.count_by_status())


if __name__ == "__main__":
    main()
