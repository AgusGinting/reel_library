"""Skema SQLite + helper baca/tulis untuk perpustakaan reel.

Tabel `reels` memegang semua data; `status` menandai sejauh mana sebuah reel
sudah diproses sehingga pipeline bisa dilanjutkan (resume):

    collected -> downloaded -> transcribed -> processed

`reels_fts` adalah indeks full-text (FTS5) yang disinkronkan via trigger.
`embeddings` menyimpan vektor untuk pencarian semantik (dipakai nanti).
"""

import csv
import sqlite3
import time

from config import DB_PATH, CSV_OUT

STATUS_ORDER = ["collected", "downloaded", "transcribed", "processed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
  shortcode   TEXT PRIMARY KEY,
  url         TEXT NOT NULL,
  author      TEXT,
  caption     TEXT,
  posted_at   TEXT,
  duration_s  REAL,
  video_path  TEXT,
  thumb_path  TEXT,
  transcript  TEXT,
  screen_text TEXT,
  summary     TEXT,
  title       TEXT,
  topics      TEXT,
  category    TEXT,
  is_learning INTEGER,
  status      TEXT NOT NULL DEFAULT 'collected',
  first_seen  TEXT,
  updated_at  TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS reels_fts USING fts5(
  caption, transcript, screen_text, summary,
  content='reels', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS reels_ai AFTER INSERT ON reels BEGIN
  INSERT INTO reels_fts(rowid, caption, transcript, screen_text, summary)
  VALUES (new.rowid, new.caption, new.transcript, new.screen_text, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS reels_ad AFTER DELETE ON reels BEGIN
  INSERT INTO reels_fts(reels_fts, rowid, caption, transcript, screen_text, summary)
  VALUES ('delete', old.rowid, old.caption, old.transcript, old.screen_text, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS reels_au AFTER UPDATE ON reels BEGIN
  INSERT INTO reels_fts(reels_fts, rowid, caption, transcript, screen_text, summary)
  VALUES ('delete', old.rowid, old.caption, old.transcript, old.screen_text, old.summary);
  INSERT INTO reels_fts(rowid, caption, transcript, screen_text, summary)
  VALUES (new.rowid, new.caption, new.transcript, new.screen_text, new.summary);
END;

CREATE TABLE IF NOT EXISTS embeddings (
  shortcode TEXT PRIMARY KEY,
  vector    BLOB,
  model     TEXT
);
"""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = connect()
    with conn:
        _migrate(conn)
        conn.executescript(SCHEMA)
    conn.close()


def _migrate(conn):
    """Upgrade DB lama ke skema terbaru."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(reels)")}
    if not cols:
        return
    # Kolom hasil AI (tahap 3b); tidak ikut FTS.
    for col, typ in (("title", "TEXT"), ("is_learning", "INTEGER")):
        if col not in cols:
            conn.execute(f"ALTER TABLE reels ADD COLUMN {col} {typ}")
    if "screen_text" in cols:
        return
    # screen_text ikut FTS -> tambah kolom lalu bangun ulang indeksnya.
    conn.execute("ALTER TABLE reels ADD COLUMN screen_text TEXT")
    conn.executescript("""
        DROP TRIGGER IF EXISTS reels_ai;
        DROP TRIGGER IF EXISTS reels_ad;
        DROP TRIGGER IF EXISTS reels_au;
        DROP TABLE IF EXISTS reels_fts;
    """)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO reels_fts(reels_fts) VALUES ('rebuild')")


def add_collected(reels):
    """Tambah reel baru (status=collected). `reels` = iterable dict
    berisi shortcode, url, first_seen. Tidak menimpa data yang sudah ada.
    Mengembalikan jumlah baris baru."""
    conn = connect()
    added = 0
    with conn:
        for r in reels:
            cur = conn.execute(
                "INSERT OR IGNORE INTO reels (shortcode, url, status, first_seen, updated_at) "
                "VALUES (?, ?, 'collected', ?, ?)",
                (r["shortcode"], r["url"], r.get("first_seen", now()), now()),
            )
            added += cur.rowcount
    conn.close()
    return added


def get_reel(shortcode):
    conn = connect()
    row = conn.execute("SELECT * FROM reels WHERE shortcode = ?", (shortcode,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_by_status(status):
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM reels WHERE status = ? ORDER BY first_seen", (status,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_reel(shortcode, **fields):
    """Perbarui kolom sembarang untuk satu reel + updated_at."""
    if not fields:
        return
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = connect()
    with conn:
        conn.execute(
            f"UPDATE reels SET {cols} WHERE shortcode = ?",
            (*fields.values(), shortcode),
        )
    conn.close()


def count_by_status():
    conn = connect()
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM reels GROUP BY status"
    ).fetchall()
    conn.close()
    return {r["status"]: r["n"] for r in rows}


def total():
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0]
    conn.close()
    return n


def export_csv(path=CSV_OUT):
    """Ekspor isi tabel reels ke CSV untuk transparansi."""
    conn = connect()
    rows = conn.execute("SELECT * FROM reels ORDER BY first_seen").fetchall()
    conn.close()
    if not rows:
        return 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))
    return len(rows)


def import_captured_csv(path=CSV_OUT):
    """Impor hasil lama diagnose.py (captured_reels.csv) ke DB.
    Menyaring sampah dengan is_valid_shortcode. Mengembalikan jumlah baru."""
    from collect import is_valid_shortcode  # hindari import melingkar saat modul dimuat

    import os
    if not os.path.exists(path):
        return 0
    batch = []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("shortcode") or "").strip()
            if not is_valid_shortcode(code, row.get("source_path", "")):
                continue
            batch.append({
                "shortcode": code,
                "url": f"https://www.instagram.com/reel/{code}/",
                "first_seen": row.get("first_seen", now()),
            })
    return add_collected(batch)


if __name__ == "__main__":
    init_db()
    print(f"DB siap: {DB_PATH}")
    print("Status:", count_by_status())
