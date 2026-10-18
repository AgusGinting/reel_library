"""Tahap 4 — Server web perpustakaan (Flask) untuk frontend React di frontend/.

Menyediakan:
  /api/status            ringkasan isi + apakah API key Claude tersedia
  /api/reels             daftar item (cari FTS, filter kategori / materi belajar)
  /api/reels/<sc>        detail satu item + daftar media (video / slide)
  /media/<sc>/<file>     file video/gambar (mendukung Range -> video bisa di-seek)
  /api/chat              tanya jawab AI (Server-Sent Events, jawaban mengalir)
  /api/chats[/<id>]      riwayat percakapan (daftar, buka, hapus)
  /api/models            model chat yang bisa dipilih (Claude / Ollama) + ketersediaannya
  /api/add               tambah link manual -> diproses di latar belakang
  /api/jobs/<id>         progres penambahan link
  /api/pending, /api/retry   item yang belum selesai + proses ulang (unduhan gagal)
  /api/instagram[/login] status sesi Instagram + buka jendela login
  /                      hasil build frontend (frontend/dist)

Jalankan:
    python library.py      # lalu buka http://127.0.0.1:5000
"""

import json
import queue
import re
import subprocess
import sys
import threading
import uuid

import anthropic
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import db
import download
import links
import ollama_chat
import pipeline
from ask import claude_librarian
from config import BASE, CHAT_MODELS, DATA, DEFAULT_CHAT_MODEL, has_api_key
from links import SC_RE

DIST = BASE / "frontend" / "dist"
MEDIA_RE = re.compile(r"^(video|slide_\d+|frames)\.(mp4|jpe?g|png|webp)$", re.I)
VIDEO_EXT = (".mp4",)

app = Flask(__name__, static_folder=None)


# --- helper -------------------------------------------------------------

def media_url(sc, path):
    if not path:
        return None
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f"/media/{sc}/{name}" if MEDIA_RE.match(name) else None


def fallback_title(row):
    text = (row["caption"] or row["screen_text"] or "").strip()
    first = text.splitlines()[0] if text else row["shortcode"]
    return first[:80] + ("…" if len(first) > 80 else "")


def card(row, snippet=None):
    return {
        "shortcode": row["shortcode"],
        "title": row["title"] or fallback_title(row),
        "author": row["author"],
        "category": row["category"],
        "is_learning": None if row["is_learning"] is None else bool(row["is_learning"]),
        "topics": json.loads(row["topics"]) if row["topics"] else [],
        "posted_at": row["posted_at"],
        "thumb": media_url(row["shortcode"], row["thumb_path"]),
        # Postingan foto/carousel memakai slide_NN sebagai thumbnail; selain itu video.
        "kind": "carousel" if "slide_" in (row["thumb_path"] or "") else "video",
        "status": row["status"],
        "snippet": snippet,
    }


def fts_query(text):
    """Ubah input bebas jadi query FTS5 aman: tiap kata dicari sebagai awalan."""
    words = re.findall(r"\w+", text, re.UNICODE)
    return " ".join(f'"{w}"*' for w in words)


def list_media(sc):
    folder = DATA / sc
    if not folder.is_dir():
        return []
    items = []
    for p in sorted(folder.iterdir()):
        if not MEDIA_RE.match(p.name) or p.stem == "frames":
            continue
        is_video = p.suffix.lower() in VIDEO_EXT
        if p.stem == "video" and not is_video:
            continue   # video.jpg = thumbnail reel, bukan konten
        items.append({"type": "video" if is_video else "image",
                      "url": f"/media/{sc}/{p.name}"})
    return items


# --- API ----------------------------------------------------------------

@app.get("/api/status")
def status():
    conn = db.connect()
    cats = conn.execute(
        "SELECT category, COUNT(*) n FROM reels WHERE category IS NOT NULL "
        "GROUP BY category ORDER BY n DESC").fetchall()
    learning = conn.execute(
        "SELECT COUNT(*) FROM reels WHERE is_learning = 1").fetchone()[0]
    conn.close()
    return jsonify({
        "total": db.total(),
        "by_status": db.count_by_status(),
        "learning": learning,
        "categories": [{"name": c["category"], "count": c["n"]} for c in cats],
        "ai_ready": has_api_key(quiet=True),
    })


@app.get("/api/reels")
def reels():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    learning = request.args.get("learning", "all")

    where, params = [], []
    if category:
        where.append("r.category = ?")
        params.append(category)
    if learning in ("1", "0"):
        where.append("r.is_learning = ?")
        params.append(int(learning))

    conn = db.connect()
    match = fts_query(q) if q else ""
    if match:
        sql = ("SELECT r.*, snippet(reels_fts, -1, '[[', ']]', '…', 14) AS snip "
               "FROM reels_fts JOIN reels r ON r.rowid = reels_fts.rowid "
               "WHERE reels_fts MATCH ?" + "".join(f" AND {w}" for w in where) +
               " ORDER BY rank LIMIT 300")
        rows = conn.execute(sql, [match, *params]).fetchall()
    else:
        sql = ("SELECT r.*, NULL AS snip FROM reels r" +
               (" WHERE " + " AND ".join(where) if where else "") +
               " ORDER BY coalesce(r.posted_at, '') DESC LIMIT 300")
        rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([card(r, r["snip"]) for r in rows])


@app.get("/api/reels/<sc>")
def reel_detail(sc):
    if not SC_RE.match(sc):
        abort(404)
    conn = db.connect()
    row = conn.execute("SELECT * FROM reels WHERE shortcode = ?", (sc,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    data = card(row)
    data.update({
        "url": row["url"],
        "summary": row["summary"],
        "caption": row["caption"],
        "transcript": row["transcript"],
        "screen_text": row["screen_text"],
        "duration_s": row["duration_s"],
        "media": list_media(sc),
    })
    return jsonify(data)


@app.get("/media/<sc>/<name>")
def media(sc, name):
    if not SC_RE.match(sc) or not MEDIA_RE.match(name):
        abort(404)
    # conditional=True (default) -> mendukung Range, video bisa di-seek.
    return send_from_directory(DATA / sc, name, max_age=86400)


# --- Chat AI (Server-Sent Events) ---------------------------------------

_sessions = {}           # conversation_id -> Librarian aktif (riwayat lengkap tersimpan di DB)
_sessions_lock = threading.Lock()


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _public_refs(refs):
    return {k: {"shortcode": v["shortcode"], "title": v["title"]} for k, v in refs.items()}


MODELS = {m["id"]: m for m in CHAT_MODELS}


def _ollama_name(name):
    return name if ":" in name.split("/")[-1] else f"{name}:latest"


def _model_status(model):
    """(tersedia?, alasan bila tidak). Ollama dicek sekali per panggilan /api/models."""
    if model["provider"] == "anthropic":
        return (True, None) if has_api_key(quiet=True) else (False, "API key Claude belum diatur (.env)")
    installed = ollama_chat.installed_models()
    if installed is None:
        return False, "Ollama tidak berjalan — buka aplikasi Ollama"
    if _ollama_name(model["model"]) not in installed:
        return False, f"Belum di-pull: jalankan  ollama pull {model['model']}"
    return True, None


def _new_librarian(model_id, refs=None, history=None):
    model = MODELS[model_id]
    if model["provider"] == "anthropic":
        return claude_librarian(model_id, refs=refs, history=history)
    return ollama_chat.OllamaLibrarian(model["model"], model_id=model_id,
                                       refs=refs, history=history)


def _get_session(cid, model_id):
    """Librarian untuk percakapan `cid` dengan model `model_id`: dari memori,
    dipulihkan dari riwayat tersimpan (server restart, percakapan lama dibuka, atau
    model diganti di tengah percakapan), atau percakapan baru."""
    with _sessions_lock:
        lib = _sessions.get(cid)
        busy = lib is not None and lib.lock.locked()   # jangan ganti saat masih menjawab
        if lib is None or (lib.model_id != model_id and not busy):
            saved = db.get_chat(cid) if cid else None
            if saved:
                lib = _new_librarian(model_id, refs=saved["refs"], history=saved["messages"])
            else:
                cid = cid or uuid.uuid4().hex
                lib = _new_librarian(model_id)
            lib.lock = threading.Lock()
            _sessions[cid] = lib
        return lib, cid


class _Turn:
    """Satu jawaban yang sedang dibuat; bisa ditonton oleh beberapa stream SSE."""

    def __init__(self, question):
        self.question = question
        self.chunks = []
        self.final = None            # ("done"|"error", data) setelah selesai
        self.cond = threading.Condition()

    @property
    def text(self):
        return "".join(self.chunks)

    def push(self, chunk):
        with self.cond:
            self.chunks.append(chunk)
            self.cond.notify_all()

    def finish(self, event, data):
        with self.cond:
            self.final = (event, data)
            self.cond.notify_all()

    def wait(self, sent):
        """Tunggu potongan baru setelah indeks `sent`; kembalikan (potongan, final)."""
        with self.cond:
            while len(self.chunks) <= sent and not self.final:
                self.cond.wait()
            return self.chunks[sent:], self.final


def _answer(lib, cid, turn):
    try:
        for text in lib.stream(turn.question):
            turn.push(text)
        u = lib.usage
        sources = [{"ref": ref, **lib.refs[ref]} for ref in lib.cited]
        usage = {"input": u.input_tokens, "output": u.output_tokens,
                 "cache_read": u.cache_read_input_tokens or 0,
                 "cache_write": u.cache_creation_input_tokens or 0}
        db.add_chat_turn(cid, turn.question, lib.answer, sources, usage, lib.refs,
                         model=lib.model_id)
        turn.finish("done", {"sources": sources, "usage": usage, "model": lib.model_id})
    except anthropic.AuthenticationError:
        turn.finish("error", {"message": "API key tidak valid. Periksa file .env."})
    except anthropic.APIError as exc:
        turn.finish("error", {"message": f"Gagal menghubungi Claude: {exc}"})
    except Exception as exc:   # OllamaError, jaringan, dll.
        turn.finish("error", {"message": str(exc) or repr(exc)})
    finally:
        lib.pending = None
        lib.lock.release()


@app.get("/api/models")
def models():
    out = []
    for m in CHAT_MODELS:
        ok, why = _model_status(m)
        out.append({"id": m["id"], "label": m["label"], "note": m["note"],
                    "provider": m["provider"], "available": ok, "reason": why})
    return jsonify({"models": out, "default": DEFAULT_CHAT_MODEL})


@app.get("/api/chats")
def chats():
    return jsonify(db.list_chats())


@app.get("/api/chats/<cid>")
def chat_detail(cid):
    saved = db.get_chat(cid)
    lib = _sessions.get(cid)
    turn = getattr(lib, "pending", None)
    if not saved and not turn:
        abort(404)
    if not saved:   # pertanyaan pertama masih dijawab, belum tersimpan
        saved = {"id": cid, "title": turn.question, "messages": [], "refs": lib.refs}
    saved["refs"] = _public_refs(saved["refs"])
    # Jawaban yang masih dibuat (mis. halaman di-refresh/pindah tab di tengah jawaban).
    saved["pending"] = {"question": turn.question, "text": turn.text} if turn else None
    return jsonify(saved)


@app.delete("/api/chats/<cid>")
def chat_delete(cid):
    with _sessions_lock:
        _sessions.pop(cid, None)
    if not db.delete_chat(cid):
        abort(404)
    return "", 204


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Pertanyaan kosong."}), 400
    model_id = body.get("model") or DEFAULT_CHAT_MODEL
    if model_id not in MODELS:
        return jsonify({"error": f"Model tidak dikenal: {model_id}"}), 400
    ok, why = _model_status(MODELS[model_id])
    if not ok:
        return jsonify({"error": why}), 503

    lib, cid = _get_session(body.get("conversation_id"), model_id)
    if not lib.lock.acquire(blocking=False):
        return jsonify({"error": "Masih menjawab pertanyaan sebelumnya."}), 409

    # Jawaban dibuat di thread terpisah sampai selesai & disimpan, walau browser
    # terputus (tab di-refresh, dibekukan, atau ditutup). Stream SSE hanya "menonton".
    turn = _Turn(question)
    lib.pending = turn
    threading.Thread(target=_answer, args=(lib, cid, turn), daemon=True).start()

    def generate():
        # refs: id pendek di jawaban (R12) -> reel, supaya rujukan bisa diklik saat mengalir.
        yield sse("meta", {"conversation_id": cid, "refs": _public_refs(lib.refs)})
        sent = 0
        while True:
            chunks, final = turn.wait(sent)
            for text in chunks:
                yield sse("text", {"text": text})
            sent += len(chunks)
            if final:
                yield sse(*final)
                return

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Tambah link manual (diproses di latar belakang) --------------------

_jobs = {}               # job_id -> {"id", "done", "items": [...]}
_jobs_lock = threading.Lock()
_job_queue = queue.Queue()
_worker = None


def _job_view(job):
    with _jobs_lock:
        return {"id": job["id"], "done": job["done"],
                "items": [dict(it) for it in job["items"]]}


def _set(item, **fields):
    with _jobs_lock:
        item.update(fields)


def _run_job(job):
    by_sc = {}
    for it in job["items"]:
        try:
            if not it["shortcode"]:
                _set(it, stage="resolve")
                resolved = links.resolve(it)
                _set(it, shortcode=resolved["shortcode"], url=resolved["url"])
            row = db.get_reel(it["shortcode"])
            if row and row["status"] == "processed":
                _set(it, stage="exists", title=row["title"] or fallback_title(row))
                continue
            if not row:
                db.add_collected([{"shortcode": it["shortcode"], "url": it["url"]}])
            by_sc[it["shortcode"]] = it
        except Exception as exc:
            _set(it, stage="error", message=pipeline.short_error(exc))
    if not by_sc:
        return

    def on_event(sc, stage, message=None):
        if sc in by_sc:
            _set(by_sc[sc], stage=stage, **({"message": message} if message else {}))

    pipeline.run(only=list(by_sc), on_event=on_event)

    for sc, it in by_sc.items():
        if it["stage"] == "error":
            continue
        row = db.get_reel(sc)
        if row["status"] == "processed":
            _set(it, stage="done", title=row["title"])
        else:
            why = "" if has_api_key(quiet=True) else " (API key Claude belum diatur)"
            _set(it, stage="partial", title=fallback_title(row),
                 message=f"Berhenti di tahap '{row['status']}'{why}")


def _work():
    while True:
        job = _job_queue.get()
        try:
            _run_job(job)
        except Exception as exc:   # mis. cookies gagal diekspor -> semua item gagal
            for it in job["items"]:
                if it["stage"] not in ("done", "exists", "error", "partial"):
                    _set(it, stage="error", message=pipeline.short_error(exc))
        finally:
            with _jobs_lock:
                job["done"] = True


def _enqueue(items):
    """Buat job baru dari item {input, shortcode, url} dan masukkan ke antrean."""
    global _worker
    job = {"id": uuid.uuid4().hex, "done": False,
           "items": [{**it, "stage": "queued", "message": None, "title": None} for it in items]}
    with _jobs_lock:
        _jobs[job["id"]] = job
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True)
            _worker.start()
    _job_queue.put(job)
    return job


def _active_shortcodes():
    with _jobs_lock:
        return {it["shortcode"] for job in _jobs.values() if not job["done"]
                for it in job["items"] if it["shortcode"]}


@app.post("/api/add")
def add_links():
    body = request.get_json(silent=True) or {}
    items = links.parse_links(body.get("text", ""))
    if not items:
        return jsonify({"error": "Tidak ada link yang dikenali. Tempel link yang diawali https://"}), 400
    if len(items) > 50:
        return jsonify({"error": "Maksimal 50 link sekali tambah."}), 400
    return jsonify(_job_view(_enqueue(items))), 202


@app.get("/api/pending")
def pending():
    """Item yang belum selesai diproses (mis. unduhan gagal) — bisa dicoba lagi."""
    active = _active_shortcodes()
    conn = db.connect()
    rows = conn.execute("SELECT * FROM reels WHERE status != 'processed' "
                        "ORDER BY first_seen DESC").fetchall()
    conn.close()
    return jsonify([{"shortcode": r["shortcode"], "url": r["url"], "status": r["status"],
                     "title": fallback_title(r) if (r["caption"] or r["screen_text"]) else r["url"],
                     "running": r["shortcode"] in active} for r in rows])


@app.post("/api/retry")
def retry():
    """Proses ulang item yang belum selesai: {"shortcodes": [...]} (dilanjutkan dari
    tahap terakhirnya, mis. unduhan yang gagal diulang)."""
    codes = (request.get_json(silent=True) or {}).get("shortcodes") or []
    active = _active_shortcodes()
    items = []
    for sc in dict.fromkeys(codes):
        row = db.get_reel(sc) if isinstance(sc, str) else None
        if row and row["status"] != "processed" and sc not in active:
            items.append({"input": row["url"], "shortcode": sc, "url": row["url"]})
    if not items:
        return jsonify({"error": "Tidak ada item yang perlu dicoba lagi."}), 400
    return jsonify(_job_view(_enqueue(items))), 202


# --- Login Instagram (sesi habis) ---------------------------------------

_login_proc = None


@app.get("/api/instagram")
def instagram_status():
    running = _login_proc is not None and _login_proc.poll() is None
    return jsonify({"logged_in": download.instagram_logged_in(), "login_running": running})


@app.post("/api/instagram/login")
def instagram_login():
    """Buka jendela Chromium untuk login Instagram (login.py) di komputer ini."""
    global _login_proc
    if _login_proc is None or _login_proc.poll() is not None:
        _login_proc = subprocess.Popen([sys.executable, str(BASE / "login.py")], cwd=str(BASE))
    return jsonify({"login_running": True}), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify(_job_view(job))


# --- Frontend (hasil build React) ---------------------------------------

@app.get("/")
@app.get("/<path:path>")
def frontend(path=""):
    if path.startswith(("api/", "media/")):
        abort(404)
    if not (DIST / "index.html").exists():
        return ("Frontend belum di-build. Jalankan: cd frontend && npm install && "
                "npm run build", 200, {"Content-Type": "text/plain; charset=utf-8"})
    if path and (DIST / path).is_file():
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")


if __name__ == "__main__":
    db.init_db()
    print("Perpustakaan: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
