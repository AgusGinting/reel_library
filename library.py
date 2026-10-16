"""Tahap 4 — Server web perpustakaan (Flask) untuk frontend React di frontend/.

Menyediakan:
  /api/status            ringkasan isi + apakah API key Claude tersedia
  /api/reels             daftar item (cari FTS, filter kategori / materi belajar)
  /api/reels/<sc>        detail satu item + daftar media (video / slide)
  /media/<sc>/<file>     file video/gambar (mendukung Range -> video bisa di-seek)
  /api/chat              tanya jawab AI (Server-Sent Events, jawaban mengalir)
  /api/add               tambah link manual -> diproses di latar belakang
  /api/jobs/<id>         progres penambahan link
  /                      hasil build frontend (frontend/dist)

Jalankan:
    python library.py      # lalu buka http://127.0.0.1:5000
"""

import json
import queue
import re
import threading
import uuid

import anthropic
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import db
import links
import pipeline
from ask import Librarian
from config import BASE, DATA, has_api_key
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

_sessions = {}           # conversation_id -> Librarian (riwayat percakapan)
_sessions_lock = threading.Lock()


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Pertanyaan kosong."}), 400
    if not has_api_key(quiet=True):
        return jsonify({"error": "API key Claude belum diatur (file .env)."}), 503

    with _sessions_lock:
        cid = body.get("conversation_id")
        lib = _sessions.get(cid)
        if lib is None:
            cid = uuid.uuid4().hex
            lib = _sessions[cid] = Librarian()
            lib.lock = threading.Lock()

    def generate():
        # refs: id pendek di jawaban (R12) -> reel, supaya rujukan bisa diklik saat mengalir.
        refs = {k: {"shortcode": v["shortcode"], "title": v["title"]} for k, v in lib.refs.items()}
        yield sse("meta", {"conversation_id": cid, "refs": refs})
        if not lib.lock.acquire(blocking=False):
            yield sse("error", {"message": "Masih menjawab pertanyaan sebelumnya."})
            return
        try:
            for text in lib.stream(question):
                yield sse("text", {"text": text})
            u = lib.usage
            yield sse("done", {
                "sources": [{"ref": ref, **lib.refs[ref]} for ref in lib.cited],
                "usage": {"input": u.input_tokens, "output": u.output_tokens,
                          "cache_read": u.cache_read_input_tokens or 0,
                          "cache_write": u.cache_creation_input_tokens or 0},
            })
        except anthropic.AuthenticationError:
            yield sse("error", {"message": "API key tidak valid. Periksa file .env."})
        except anthropic.APIError as exc:
            yield sse("error", {"message": f"Gagal menghubungi Claude: {exc}"})
        finally:
            lib.lock.release()

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


@app.post("/api/add")
def add_links():
    global _worker
    body = request.get_json(silent=True) or {}
    items = links.parse_links(body.get("text", ""))
    if not items:
        return jsonify({"error": "Tidak ada link yang dikenali. Tempel link yang diawali https://"}), 400
    if len(items) > 50:
        return jsonify({"error": "Maksimal 50 link sekali tambah."}), 400

    job = {"id": uuid.uuid4().hex, "done": False,
           "items": [{**it, "stage": "queued", "message": None, "title": None} for it in items]}
    with _jobs_lock:
        _jobs[job["id"]] = job
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True)
            _worker.start()
    _job_queue.put(job)
    return jsonify(_job_view(job)), 202


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
