"""Jalankan item baru melewati semua tahap sampai masuk perpustakaan:

    collected --unduh--> downloaded --transkrip--> transcribed
              --OCR (item tanpa ucapan)--> --katalog Claude--> processed

Dipakai oleh add.py (CLI) dan tombol "Tambah" di web (library.py). Sama seperti
skrip per tahap, item yang sudah lewat suatu tahap tidak diproses ulang.

Jalankan langsung untuk memproses semua item yang belum selesai (mis. setelah collect.py):
    python pipeline.py
"""

import anthropic

import db
import download
import ocr
import process
import summarize
from config import WHISPER_COMPUTE, WHISPER_DEVICE, WHISPER_MODEL, has_api_key


def short_error(exc):
    lines = (str(exc) or repr(exc)).splitlines()
    return lines[0][:200] if lines else repr(exc)


def run(only=None, log=print, on_event=None):
    """Proses item yang belum selesai. `only` membatasi ke shortcode tertentu.
    on_event(shortcode, stage, message=None) dipanggil saat tiap item masuk tahap
    download | transcribe | ocr | summarize, atau 'error' bila tahapnya gagal."""
    only = set(only) if only else None
    emit = on_event or (lambda sc, stage, message=None: None)

    def pending(status):
        return [r for r in db.get_by_status(status) if only is None or r["shortcode"] in only]

    def fail(sc, stage, exc):
        log(f"GAGAL {stage} {sc}: {short_error(exc)}")
        emit(sc, "error", f"Gagal saat {stage}: {short_error(exc)}")

    db.init_db()

    items = pending("collected")
    if items:
        download.ensure_cookies(log=log)
        for r in items:
            emit(r["shortcode"], "download")
            try:
                log(f"unduh {r['shortcode']}: {download.download_reel(r)}")
            except Exception as exc:
                fail(r["shortcode"], "mengunduh", exc)

    items = pending("downloaded")
    if items:
        process.enable_cuda_dlls()
        model = process.load_model(WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE)
        try:
            for r in items:
                emit(r["shortcode"], "transcribe")
                try:
                    text, lang = process.transcribe_reel(model, r)
                    log(f"transkrip {r['shortcode']}: {lang}, {len(text)} karakter")
                except Exception as exc:
                    fail(r["shortcode"], "transkrip", exc)
        finally:
            del model   # bebaskan memori GPU

    if not has_api_key(quiet=True):
        log("API key Claude belum diatur: OCR & katalog dilewati.")
        return
    client = anthropic.Anthropic()

    for r in ocr.targets():
        if only is not None and r["shortcode"] not in only:
            continue
        emit(r["shortcode"], "ocr")
        try:
            text = ocr.auto_ocr(client, r)
            log(f"OCR {r['shortcode']}: {len(text)} karakter")
        except Exception as exc:
            # Tetap lanjut ke katalog; caption saja masih berguna.
            log(f"Peringatan OCR {r['shortcode']}: {short_error(exc)}")

    for r in pending("transcribed"):
        emit(r["shortcode"], "summarize")
        try:
            data, _ = summarize.catalog(client, r)
            summarize.save(r, data)
            log(f"katalog {r['shortcode']}: {data['title']}")
        except Exception as exc:
            fail(r["shortcode"], "meringkas", exc)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    run()
    print("Status DB:", db.count_by_status())
