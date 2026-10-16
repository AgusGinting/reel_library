# Reel Learning Library — Arsitektur

Perpustakaan pribadi berisi reel & postingan Instagram yang dikirim lewat DM.
Setiap item diubah menjadi teks (transkrip suara + teks di layar), dikatalogkan oleh
Claude (judul, ringkasan, topik, kategori, materi belajar atau bukan), lalu bisa
dicari dan ditanyai lewat web lokal.

Cara pakai ada di [README.md](README.md). Dokumen ini menjelaskan **cara kerjanya
dan alasan di balik setiap keputusan**.

## Status (2026-10-13)

| | Jumlah |
|---|---|
| Item terkumpul dari DM | 125 (104 reel video + 21 postingan foto/carousel, 117 slide) |
| Diproses penuh (`processed`) | 125 |
| Ditandai materi belajar | 79 |
| Kategori | AI & LLM 44 · Hiburan & Meme 33 · Tools & Website 19 · Tips & Lifestyle 9 · Pemrograman & Data 9 · Riset & Akademik 4 · Berita & Sosial 4 · Karier & Produktivitas 3 |
| Biaya Claude API untuk katalog | ±$1,89 (Claude Opus 5.5, effort `low`) |

## Pipeline

```
 DM Instagram                              Link manual (web "+ Tambah" / add.py)
     │  collect.py   sadap respons JSON          │  links.py: IG → shortcode; lain → id yt-dlp
     ▼               (/api/graphql) → shortcode  ▼                         status: collected
     └──────────────────────┬────────────────────┘
                            ▼   pipeline.py menjalankan tahap di bawah untuk item yang belum selesai
 download.py   reel video  → yt-dlp (+cookies.txt) → data/<sc>/video.mp4 + video.jpg
     │         foto/carousel → API media IG → data/<sc>/slide_NN.jpg|mp4    downloaded
     ▼
 process.py    faster-whisper (GPU) → transcript                         transcribed
     │         (video tanpa trek audio → transcript kosong)
     ▼
 ocr.py        item tanpa ucapan → kolase frame / slide → Claude API (vision) → screen_text
     │
     ▼
 summarize.py  Claude API (structured output) → title, summary, topics,
     │         category, is_learning                                      processed
     ▼
 library.py    Flask: API + media + chat AI   ◄──►   frontend/ (React + Vite)
 ask.py        tanya jawab dari terminal (dipakai ulang oleh library.py)
```

Kolom `status` membuat pipeline **bisa dilanjutkan kapan saja**: setiap skrip hanya
memproses item yang belum naik ke tahapnya. Menambah reel baru = jalankan ulang
semua skrip secara berurutan; item lama dilewati.

## Keputusan desain

| Aspek | Pilihan | Alasan / pelajaran |
|---|---|---|
| Ambil link dari DM | Sadap respons jaringan (Playwright `context.on("response")`) | Reel yang di-share di DM **tidak** dirender sebagai `<a href>`. Versi awal (`app.py`) yang membaca link hanya mendapat 2 link sampah. Menyadap JSON mendapat semua 126 shortcode hanya dengan scroll. |
| Login Instagram | Profil browser persisten (`browser_profile/`), login manual | Tidak menyimpan password; sesi dipakai ulang oleh semua tahap. |
| Unduh video | `yt-dlp` + `cookies.txt` yang diekspor dari profil | Andal; cookies membuka akses ke reel yang perlu login. |
| Unduh foto/carousel | API media Instagram `/api/v1/media/<id>/info/` | yt-dlp gagal ("No video formats found") untuk postingan foto. Media id = shortcode yang di-decode dari base64url. |
| Transkrip | `faster-whisper` model `small`, GPU (`int8_float16`) | Gratis & privat; RTX 3050 4 GB cukup. Bahasa dideteksi otomatis (konten campur ID/EN). |
| Teks di layar | Dibaca Claude dari kolase frame (2×2) / slide | 44 item tidak punya ucapan (musik/bisu) tetapi materinya berupa teks di layar. Batch awal dibaca Claude Code (belum ada API key); kini otomatis lewat Claude API (`ocr.py auto`) dengan aturan transkripsi yang sama. |
| Tambah link manual | `links.py` + `pipeline.py`, dipakai CLI (`add.py`) dan web (`/api/add`) | Satu jalur proses untuk semua sumber. Link Instagram dikenali dari URL; YouTube/TikTok/dll. lewat id dari yt-dlp, sehingga tabel `reels` tetap berkunci satu id. Web memproses di satu thread latar belakang (GPU tidak dipakai bersamaan) dan halaman memantau progres per link. |
| Katalog | Claude Opus 5.5, `output_config.format` JSON schema, effort `low` | JSON selalu valid; kualitas ringkasan tinggi; murah (~$0,015/item). |
| Tanya jawab | **Seluruh** perpustakaan dimuat ke system prompt + prompt caching | Terukur ±139 ribu token (125 item), jauh di bawah konteks 1 juta token. Tanpa vector DB / embedding: lebih sederhana dan tidak ada item yang terlewat oleh retrieval. Pertanyaan lanjutan dibaca dari cache (~1/25 harga input). |
| Rujukan sumber | Item diberi id pendek `R1`…`Rn` di prompt; server memetakan balik ke shortcode | Saat memakai shortcode langsung, model menukar dua id mirip (`DcRaD8vsTwR` vs `DcRJg5fDdsJ`) sehingga rujukannya salah. Dengan id pendek, 7/7 rujukan pada uji yang sama tepat. |
| Penolakan model | `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) | Jika Claude menolak, server otomatis mencoba model lain. |
| Penyimpanan & cari | SQLite + FTS5 | Satu file, tanpa server. FTS dengan pencarian awalan kata + snippet highlight. |
| Web | Flask (backend) + React/Vite (frontend) | Flask cocok dengan kode sinkron yang ada dan `send_from_directory` mendukung Range (video bisa di-seek). Frontend di-build ke `frontend/dist` dan disajikan Flask → cukup satu perintah. |

## Struktur folder

```
reel_collector/
├── collect.py          Tahap 1  GUI Tkinter + Playwright, tangkap shortcode dari DM
├── download.py         Tahap 2  yt-dlp + fallback API media (carousel); ekspor cookies
├── process.py          Tahap 3  transkrip Whisper (GPU)
├── ocr.py              Tahap 3  OCR teks layar (auto via Claude API, atau kolase + impor manual)
├── summarize.py        Tahap 3b katalog dengan Claude API
├── pipeline.py         jalankan semua tahap untuk item yang belum selesai
├── links.py            kenali link manual (Instagram / TikTok / yt-dlp)
├── tiktok.py           link pendek & slideshow foto TikTok
├── add.py              CLI tambah link manual
├── ask.py              Tahap 4  tanya jawab (CLI) — kelas Librarian dipakai web
├── library.py          Tahap 4  server Flask
├── db.py               skema SQLite, migrasi, helper
├── config.py           path, model, pemuat .env
├── frontend/           React + Vite (src/, dist/ hasil build)
├── data/<shortcode>/   video.mp4, video.jpg, slide_NN.*, frames.jpg, transcript.txt
├── library.db          database utama
├── browser_profile/    sesi login Instagram (RAHASIA)
├── cookies.txt         cookies Instagram hasil ekspor (RAHASIA)
├── .env                ANTHROPIC_API_KEY (RAHASIA)
│
│   Sisa versi awal (tidak dipakai lagi, aman dihapus):
├── app.py, reels.csv              pengumpul link versi <a href> (gagal)
├── diagnose.py, diagnostic_report.txt   alat diagnosa yang menjadi cikal bakal collect.py
└── captured_reels.csv             ekspor CSV dari tabel reels (bisa dibuat ulang)
```

## Skema database

```sql
CREATE TABLE reels (
  shortcode   TEXT PRIMARY KEY,   -- id Instagram (base64url)
  url         TEXT NOT NULL,      -- /reel/<sc>/ atau /p/<sc>/ (carousel)
  author      TEXT,
  caption     TEXT,
  posted_at   TEXT,               -- YYYY-MM-DD
  duration_s  REAL,
  video_path  TEXT,               -- NULL untuk carousel tanpa video
  thumb_path  TEXT,
  transcript  TEXT,               -- Whisper; '' bila tanpa ucapan
  screen_text TEXT,               -- OCR teks di layar (hanya item tanpa ucapan)
  summary     TEXT,               -- ringkasan + "Poin penting:" (markdown)
  title       TEXT,
  topics      TEXT,               -- JSON array
  category    TEXT,               -- salah satu dari 8 kategori di summarize.py
  is_learning INTEGER,            -- 1 materi belajar, 0 bukan
  status      TEXT NOT NULL,      -- collected | downloaded | transcribed | processed
  first_seen  TEXT,
  updated_at  TEXT
);

-- FTS5 external-content, disinkronkan oleh trigger insert/update/delete
CREATE VIRTUAL TABLE reels_fts USING fts5(
  caption, transcript, screen_text, summary,
  content='reels', content_rowid='rowid'
);

CREATE TABLE embeddings (...);    -- disiapkan, belum dipakai
```

`db.init_db()` menjalankan migrasi otomatis (`_migrate`) untuk database lama:
menambah kolom baru dan membangun ulang indeks FTS bila perlu.

## Detail tiap tahap

### 1. Kumpulkan — `collect.py`
- Membuka Chromium dengan `browser_profile/`; pengguna login dan membuka DM sendiri.
- Saat "Mulai Rekam", setiap respons JSON dari instagram.com dipindai dengan regex
  `"shortcode":"…"`, `"code":"…"`, dan path `/(reel|reels|p)/…`.
- Penyaring `is_valid_shortcode`: menolak kata route (mis. `audio`) dan token < 9 karakter.
- Event respons hanya dipompa ketika ada panggilan Playwright, karena itu loop worker
  memanggil `page.wait_for_timeout(500)`.

### 2. Unduh — `download.py`
- Setiap kali jalan: ekspor cookies dari profil (Chromium headless) → `cookies.txt`.
  Profil **tidak boleh** sedang dipakai `collect.py`.
- Reel: yt-dlp → `video.mp4` + thumbnail `video.jpg` + metadata.
- Bila yt-dlp gagal (`DownloadError`) → `download_slides()`: ambil `carousel_media`
  dari API media, simpan setiap slide. Item tanpa video langsung berstatus
  `transcribed` (tidak ada audio untuk ditranskrip).
- Jeda acak 3–8 detik antar item agar tidak diblokir.

### 3. Transkrip — `process.py`
- CUDA di Windows: `enable_cuda_dlls()` menambahkan semua folder `nvidia/*/bin`
  (dari paket pip `nvidia-*-cu12`) ke `PATH` **dan** `os.add_dll_directory`.
  `add_dll_directory` saja tidak cukup karena cublas memuat cudart secara berantai.
- `has_audio()` memeriksa trek audio lebih dulu; PyAV melempar `IndexError` pada video bisu.
- Fallback otomatis ke CPU (`int8`) bila GPU gagal dimuat.

### 3. Teks di layar — `ocr.py`
- Sasaran: item `transcribed` dengan transkrip < 20 karakter dan `screen_text` kosong.
- Untuk video, ffmpeg membuat `frames.jpg` (4 frame merata, kolase 2×2); untuk
  carousel, `slide_NN.jpg` dipakai langsung (maks. 20 gambar per item).
- `ocr.py auto` (dan `pipeline.py`): gambar dikirim ke Claude API (effort `low`) dengan
  instruksi transkripsi kata per kata per gambar `[n]` + catatan `[Visual: …]`.
- Jalur manual tanpa API key tetap ada: `ocr.py frames` → baca dengan Claude Code →
  `ocr.py import <file.json>`.

### Tambah link manual — `links.py`, `pipeline.py`, `add.py`
- `parse_links()` mengambil semua URL dari teks bebas; URL Instagram dinormalkan ke
  `/reel/<sc>/` atau `/p/<sc>/` (parameter `?igsh=` dan nama akun di path dibuang).
- `resolve()` untuk link lain: `yt_dlp.extract_info(download=False)` → id (bila tidak
  cocok pola id, diberi awalan nama extractor). Playlist ditolak.
- **TikTok** (`tiktok.py`): link pendek (`vm.`/`vt.tiktok.com`, `tiktok.com/t/`) dibuka
  redirect-nya sendiri; redirect ke beranda = postingan mati → pesan jelas. Video biasa
  diunduh yt-dlp. Slideshow foto (`/photo/<id>`) **tidak dikenali yt-dlp**, sehingga
  gambarnya diambil dari JSON `__UNIVERSAL_DATA_FOR_REHYDRATION__` di halaman
  (`webapp.video-detail → itemInfo.itemStruct.imagePost.images[].imageURL.urlList`),
  dikonversi ke JPEG bila perlu, dan disimpan sebagai `slide_NN.jpg` (lalu OCR seperti
  carousel). Slideshow yang dibagikan dengan URL `/video/` terdeteksi saat yt-dlp tidak
  menghasilkan file video (`NoVideoFile`).
- TikTok sesekali membalas **HTTP 403/429** untuk akses beruntun (terbukti: link yang sama
  berhasil, lalu 403, lalu berhasil lagi beberapa menit kemudian). Unduhan & pembacaan
  halaman dicoba ulang 3× dengan jeda 10/20 detik; `curl_cffi` dipasang sesuai anjuran
  yt-dlp. Postingan yang dibatasi wilayah ("IP address is blocked") memang tidak bisa diambil.
- `download_one()` memaksa format mp4 (`bv*[ext=mp4]+ba[ext=m4a]/…`, merge ke mp4) agar
  video YouTube dkk. bisa diputar & di-seek di web, dan mengonversi thumbnail ke JPG
  (TikTok memberi berkas `.image`, YouTube `.webp`).
- `download.ensure_cookies()` hanya mengekspor ulang cookies bila `cookies.txt` lebih
  tua dari 12 jam, supaya menambah satu link tidak selalu membuka Chromium.
- `pipeline.run(only=[...], on_event=...)` menjalankan unduh → transkrip → OCR → katalog
  hanya untuk item yang diminta dan melaporkan tahap tiap item lewat `on_event`.

### 3b. Katalog — `summarize.py`
- Input: pengunggah, caption, transkrip, teks layar. Output (JSON schema): `title`,
  `summary`, `key_points[]`, `topics[]`, `category` (enum 8), `is_learning`.
- `key_points` digabung ke `summary` sebagai daftar "Poin penting" agar ikut terindeks FTS.
- Prompt meminta model tidak mengarang dan menandai nama yang mungkin salah dengar.

### 4. Tanya jawab — `ask.py` + `library.py`
- `build_library()` menyusun semua item sebagai `<item id="R12" judul kategori materi_belajar>…`
  dengan urutan tetap (berdasarkan shortcode) agar cache tidak pecah, dan mengembalikan
  peta `refs` (`R12` → shortcode, judul, url). Id `R` hanya berlaku dalam satu percakapan.
- System prompt = instruksi + blok perpustakaan dengan `cache_control: ephemeral`.
- `Librarian.stream()` menghasilkan potongan teks; riwayat menyimpan `response.content`
  utuh (termasuk blok thinking) supaya percakapan bisa berlanjut.
- Rujukan `[R12]` di jawaban diekstrak menjadi `cited`; web menerima peta `refs` di event
  `meta` sehingga rujukan sudah bisa diklik (berlabel judul) selama jawaban mengalir.

### 4. Web — `library.py` + `frontend/`

| Endpoint | Fungsi |
|---|---|
| `GET /api/status` | total, status, jumlah materi belajar, kategori, `ai_ready` |
| `GET /api/reels?q=&category=&learning=1\|0\|all` | daftar kartu; `q` → FTS (`"kata"*` per kata, urut `rank`, snippet dengan penanda `[[ ]]`) |
| `GET /api/reels/<sc>` | detail + daftar media (video / slide) |
| `GET /media/<sc>/<file>` | file media; nama dibatasi regex, mendukung Range |
| `POST /api/chat` | `{question, conversation_id?}` → Server-Sent Events: `meta` (conversation_id, refs), `text`*, `done` (sources, usage) atau `error` |
| `POST /api/add` | `{text}` (link bebas, maks. 50) → `202` + job `{id, done, items[]}`; diproses di thread latar belakang |
| `GET /api/jobs/<id>` | progres job; tiap item: `stage` = queued · resolve · download · transcribe · ocr · summarize · done · exists · partial · error, plus `message`, `title` |
| `GET /*` | `frontend/dist` (SPA) |

- Percakapan disimpan di memori server (`_sessions`, satu `Librarian` per id) dan hilang
  saat server dimatikan. Satu percakapan hanya memproses satu pertanyaan sekaligus.
- Job "tambah link" juga disimpan di memori server (`_jobs`) dan hilang saat restart;
  item yang sudah masuk DB tetap aman dan bisa dilanjutkan dengan `python pipeline.py`.
- Frontend: `App` (state, filter, pemantau job tambah link) · `Toolbar` (cari, materi
  belajar, kategori, + Tambah) · `ReelGrid` (kartu + highlight) · `ReelDetail`
  (video/slide, ringkasan, tab teks) · `ChatPanel` (stream SSE via `fetch`, rujukan bisa
  diklik, lebar bisa diseret & tersimpan di `localStorage`) · `AddDialog` (tempel link,
  progres per link) · `ErrorBoundary` (error di satu panel tidak mengosongkan halaman).
  Tema terang/gelap mengikuti sistem.

## Batasan & risiko yang diketahui

- **API internal Instagram** (graphql, media info) tidak resmi dan bisa berubah kapan saja;
  kalau `collect.py`/`download_slides()` tiba-tiba gagal, regex atau endpoint perlu dicek ulang.
- **Cookies kedaluwarsa**: kalau unduhan mulai gagal semua, login ulang lewat `collect.py`.
- **Konteks tanya jawab**: aman sampai ribuan item (konteks 1 juta token). Jika perpustakaan
  sudah sangat besar, pertimbangkan retrieval (FTS/embedding) sebelum memanggil Claude.
- Server dirancang untuk **pemakaian lokal satu orang** (`127.0.0.1`, tanpa autentikasi).

## Ide berikutnya

- [x] Otomatiskan OCR dengan Claude API (vision) di `ocr.py`.
- [x] Satu perintah `pipeline.py` yang menjalankan download → process → ocr → summarize.
- [x] Tambah materi dari link manual (web "+ Tambah" dan `add.py`).
- [ ] Unggah file video dari laptop (bukan link).
- [ ] Tombol "sembunyikan/hapus item" di web untuk membersihkan meme.
- [ ] Catatan pribadi / tandai "sudah dipelajari" per item.
