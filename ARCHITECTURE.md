# Reel Learning Library — Arsitektur

Perpustakaan pribadi berisi reel & postingan Instagram yang dikirim lewat DM.
Setiap item diubah menjadi teks (transkrip suara + teks di layar), dikatalogkan oleh
Claude (judul, ringkasan, topik, kategori, materi belajar atau bukan), lalu bisa
dicari dan ditanyai lewat web lokal.

Cara pakai ada di [README.md](README.md). Dokumen ini menjelaskan **cara kerjanya
dan alasan di balik setiap keputusan**.

## Status (2026-10-19)

| | Jumlah |
|---|---|
| Item di perpustakaan | 224 (194 reel/video Instagram + 30 postingan `/p/` foto/carousel) — dari DM dan link manual |
| Diproses penuh (`processed`) | 224 |
| Ditandai materi belajar | 174 |
| Kategori | AI & LLM 115 · Tools & Website 41 · Hiburan & Meme 33 · Pemrograman & Data 14 · Tips & Lifestyle 9 · Berita & Sosial 5 · Riset & Akademik 4 · Karier & Produktivitas 3 |
| Ukuran perpustakaan untuk chat mode penuh | 250.638 token (`messages.count_tokens`, tokenizer Sonnet/Opus/Fable/Haiku 5.5) |
| Biaya katalog awal | ±$1,89 untuk 125 item pertama (Claude Opus 5.5, effort `low`); kini `CLAUDE_MODEL` = Sonnet 5.5 |

## Pipeline

```
 DM Instagram                              Link manual (web "+ Tambah" / add.py)
     │  collect.py   sadap respons JSON          │  links.py: IG → shortcode; lain → id yt-dlp
     ▼               (/api/graphql) → shortcode  ▼                         status: collected
     └──────────────────────┬────────────────────┘
                            ▼   pipeline.py menjalankan tahap di bawah untuk item yang belum selesai
 download.py   reel video  → yt-dlp (+cookies.txt) → data/<sc>/video.mp4 + video.jpg
     │         foto/carousel IG → data anonim yt-dlp (tanpa login; API media bila privat)
     │         slideshow TikTok → data halaman TikTok → data/<sc>/slide_NN.jpg|mp4  downloaded
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
| Unduh foto/carousel | 1) **Tanpa login**: data anonim yang sudah diambil yt-dlp (`xig_polaris_media.if_not_gated_logged_out`), disadap lewat `InstagramIE._extract_product` (`download._anon_item`). 2) Bila tidak ada (privat): API media `/api/v1/media/<id>/info/` dengan login. | yt-dlp mengambil data postingan publik secara anonim lalu berhenti ("There is no video in this post") karena ia pengunduh video — datanya sudah lengkap (URL semua slide, caption, user), bentuknya sama dengan item API media. Sebelumnya hanya jalur 2 yang dipakai, sehingga semua postingan foto gagal saat sesi Instagram habis (2026-10-19). Media id = shortcode yang di-decode dari base64url. |
| Transkrip | `faster-whisper` model `small`, GPU (`int8_float16`) | Gratis & privat; RTX 3050 4 GB cukup. Bahasa dideteksi otomatis (konten campur ID/EN). |
| Teks di layar | Dibaca Claude dari kolase frame (2×2) / slide | 44 item tidak punya ucapan (musik/bisu) tetapi materinya berupa teks di layar. Batch awal dibaca Claude Code (belum ada API key); kini otomatis lewat Claude API (`ocr.py auto`) dengan aturan transkripsi yang sama. |
| Tambah link manual | `links.py` + `pipeline.py`, dipakai CLI (`add.py`) dan web (`/api/add`) | Satu jalur proses untuk semua sumber. Link Instagram dikenali dari URL; YouTube/TikTok/dll. lewat id dari yt-dlp, sehingga tabel `reels` tetap berkunci satu id. Web memproses di satu thread latar belakang (GPU tidak dipakai bersamaan) dan halaman memantau progres per link. |
| Katalog & OCR | `CLAUDE_MODEL` (kini Claude Sonnet 5.5; batch awal Opus 5.5), `output_config.format` JSON schema, effort `low` | JSON selalu valid; kualitas ringkasan tinggi; murah (~$0,015/item dengan Opus). |
| Tanya jawab | Mode **penuh**: seluruh perpustakaan di system prompt + prompt caching. Mode **pencarian** (`retrieval.py`) untuk model berkonteks kecil / gratis. | Mode penuh: 250.638 token (224 item), di bawah konteks 1 juta token; tanpa vector DB — tidak ada item yang terlewat oleh retrieval. Pertanyaan lanjutan dibaca dari cache (0,05× harga input di Opus/Sonnet 5.5, 0,025× di Fable 5.1, 0,1× di Haiku 5.5). |
| Model Claude | Haiku 4.5, Haiku 5.5, Sonnet 5.5 (bawaan `CLAUDE_MODEL`, id `claude`), Opus 5.5, Fable 5.1 — dipilih per pertanyaan | Ukuran diukur dengan `messages.count_tokens` (gratis): 250.638 token (Haiku 5.5/Sonnet/Opus/Fable), 181.510 token (tokenizer Haiku 4.5). Haiku 4.5 hanya 200K → mode pencarian; lainnya konteks 1M → mode penuh. Spesifikasi model yang belum dikenal (mis. Haiku 5.5) dicek lewat Models API (`client.models.retrieve`): konteks 1M, effort didukung. Per model di `CHAT_MODELS`: `mode`, `effort` (Haiku 4.5 menolak `output_config.effort` → `None`), `fallbacks` (server-side `fallbacks: "default"`; dimatikan untuk Haiku 4.5, teruji jalan di Haiku 5.5). Harga Haiku 5.5 bertingkat: prompt > 100K token (perpustakaan ini) memakai tarif lebih tinggi (tulis cache $0,625, baca cache $0,05, output $2,50 per juta token). Cache bersifat per model: berganti model = pertanyaan berikutnya menulis cache baru. |
| Model chat gratis | Ollama cloud `gemma4:31b-cloud` (+ `treyleo16/kimi-k3`), dipilih per pertanyaan | GPU 4 GB tidak sanggup model besar lokal. `kimi-k3:cloud` asli (2,8T, konteks 1M) membalas **402** di paket gratis. Manifest registry `treyleo16/kimi-k3` ternyata `remote_model: gemma4:31b` + system prompt yang mengaku "Kimi K3 by Moonshot AI" (diperiksa tanpa mengunduh: `registry.ollama.ai/v2/<nama>/manifests/latest` → blob config). Gemma tidak diberi seluruh perpustakaan (±250k token tiap pertanyaan menguras jatah gratis): ia menerima `<katalog>` semua judul + `<detail>` 15 item teratas hasil FTS5 (OR antar kata, tanpa stopword, digabung pertanyaan sebelumnya) ≈ 14k token, ±3 detik per jawaban. |
| Rujukan sumber | Item diberi id pendek `R1`…`Rn` di prompt; server memetakan balik ke shortcode | Saat memakai shortcode langsung, model menukar dua id mirip (`DcRaD8vsTwR` vs `DcRJg5fDdsJ`) sehingga rujukannya salah. Dengan id pendek, 7/7 rujukan pada uji yang sama tepat. |
| Penolakan model | `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) per model (`CHAT_MODELS[].fallbacks`) | Jika Claude menolak, server otomatis mencoba model lain. |
| Keadaan tampilan | `sessionStorage` (per tab) + `localStorage` lewat `frontend/src/storage.js`; jawaban chat dibuat di thread server | Chrome memuat ulang tab latar belakang saat RAM menipis (laptop 8 GB), sehingga halaman sempat "ter-reset" dan jawaban yang sedang dialirkan hilang. |
| Penyimpanan & cari | SQLite + FTS5 | Satu file, tanpa server. FTS dengan pencarian awalan kata + snippet highlight. |
| Web | Flask (backend) + React/Vite (frontend) | Flask cocok dengan kode sinkron yang ada dan `send_from_directory` mendukung Range (video bisa di-seek). Frontend di-build ke `frontend/dist` dan disajikan Flask → cukup satu perintah. |

## Struktur folder

```
reel_collector/
├── collect.py          Tahap 1  GUI Tkinter + Playwright, tangkap shortcode dari DM
├── download.py         Tahap 2  yt-dlp; carousel IG tanpa login (data anonim) / API media; cookies
├── process.py          Tahap 3  transkrip Whisper (GPU)
├── ocr.py              Tahap 3  OCR teks layar (auto via Claude API, atau kolase + impor manual)
├── summarize.py        Tahap 3b katalog dengan Claude API
├── pipeline.py         jalankan semua tahap untuk item yang belum selesai
├── links.py            kenali link manual (Instagram / TikTok / yt-dlp)
├── tiktok.py           link pendek & slideshow foto TikTok
├── add.py              CLI tambah link manual
├── login.py            login ulang Instagram (jendela Chromium) + ekspor cookies
├── ask.py              Tahap 4  tanya jawab Claude (CLI) — Librarian, penomoran R, format item
├── retrieval.py        Tahap 4  mode pencarian: katalog semua judul + detail item relevan (FTS)
├── ollama_chat.py      Tahap 4  tanya jawab via Ollama (memakai retrieval.py)
├── library.py          Tahap 4  server Flask
├── db.py               skema SQLite, migrasi, helper
├── config.py           path, CLAUDE_MODEL, CHAT_MODELS (pilihan model chat), pemuat .env
├── frontend/           React + Vite (src/, dist/ hasil build; src/storage.js = state per tab)
├── requirements.txt    versi paket Python; README.md = cara pakai; .gitignore
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

CREATE TABLE chats (id TEXT PRIMARY KEY, title, refs /* JSON */, created_at, updated_at);
CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id, role,
                            text, sources /* JSON */, usage /* JSON */,
                            model /* id model yang menjawab */, created_at);
```

`db.init_db()` menjalankan migrasi otomatis (`_migrate`) untuk database lama:
menambah kolom baru (`title`, `is_learning`, `screen_text`, `chat_messages.model`) dan
membangun ulang indeks FTS bila perlu.

## Detail tiap tahap

### 1. Kumpulkan — `collect.py`
- Membuka Chromium dengan `browser_profile/`; pengguna login dan membuka DM sendiri.
- Saat "Mulai Rekam", setiap respons JSON dari instagram.com dipindai dengan regex
  `"shortcode":"…"`, `"code":"…"`, dan path `/(reel|reels|p)/…`.
- Penyaring `is_valid_shortcode`: menolak kata route (mis. `audio`) dan token < 9 karakter.
- Event respons hanya dipompa ketika ada panggilan Playwright, karena itu loop worker
  memanggil `page.wait_for_timeout(500)`.

### 2. Unduh — `download.py`
- Cookies: `python download.py` selalu mengekspor ulang cookies dari profil (Chromium
  headless) → `cookies.txt`; `pipeline.py`/web memakai `ensure_cookies()` yang hanya
  mengekspor ulang bila sudah > 12 jam (sudah login) atau > 30 menit (belum login).
  Profil **tidak boleh** sedang dipakai `collect.py`/`login.py`.
- Reel: yt-dlp → `video.mp4` + thumbnail `video.jpg` + metadata.
- Bila yt-dlp gagal (`DownloadError`/`NoVideoFile`) pada Instagram → `download_slides()`:
  data postingan dari `_anon_item()` (tanpa login); bila kosong (privat) dan sudah login →
  API media; bila belum login → `InstagramLoginRequired` (pesan meminta login). Sisa
  `video.*` dari unduhan yang gagal di tengah dibuang; setiap slide disimpan sebagai
  `slide_NN.jpg|mp4`. Item tanpa video langsung berstatus `transcribed` (tidak ada audio).
- TikTok ditangani `_download_tiktok()` (lihat "Tambah link manual").
- CLI `download.py`: jeda acak 3–8 detik antar item agar tidak diblokir.

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
  tua dari 12 jam (30 menit bila belum login), supaya menambah satu link tidak selalu
  membuka Chromium.
- `pipeline.run(only=[...], on_event=...)` menjalankan unduh → transkrip → OCR → katalog
  hanya untuk item yang diminta dan melaporkan tahap tiap item lewat `on_event`.

### 3b. Katalog — `summarize.py`
- Input: pengunggah, caption, transkrip, teks layar. Output (JSON schema): `title`,
  `summary`, `key_points[]`, `topics[]`, `category` (enum 8), `is_learning`.
- `key_points` digabung ke `summary` sebagai daftar "Poin penting" agar ikut terindeks FTS.
- Prompt meminta model tidak mengarang dan menandai nama yang mungkin salah dengar.

### 4. Tanya jawab — `ask.py`, `retrieval.py`, `ollama_chat.py`
- `numbered_items(refs)` memberi tiap item id `R1…Rn` (urutan tetap berdasarkan shortcode
  agar cache tidak pecah; `refs` lama mempertahankan nomornya) dan mengembalikan peta
  `refs` (`R12` → shortcode, judul, url). Id `R` hanya berlaku dalam satu percakapan.
- **Mode penuh** (`build_library()`): semua item sebagai `<item id="R12" judul kategori
  materi_belajar>…`; system prompt = instruksi + blok perpustakaan (`cache_control`).
- **Mode pencarian** (`retrieval.Retriever`): system prompt = instruksi + `<katalog>` satu
  baris per item (di-cache); tiap pertanyaan membawa `<detail>` 15 item teratas hasil FTS5
  (OR antar kata tanpa stopword, digabung pertanyaan sebelumnya; teks panjang dipangkas
  1.200 karakter). Dipakai Haiku 4.5 dan semua model Ollama.
- `ask.claude_librarian(model_id)` membuat `Librarian` dari entri `CHAT_MODELS`
  (`model`, `mode`, `effort`, `fallbacks`); `ollama_chat.OllamaLibrarian` setara untuk
  Ollama (`/api/chat` streaming, `think: false`). CLI: `python ask.py --model <id> "…"`.
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
| `POST /api/chat` | `{question, conversation_id?, model?}` → Server-Sent Events: `meta` (conversation_id, refs), `text`*, `done` (sources, usage, model) atau `error`; `409` bila percakapan masih menjawab, `503` bila model tidak tersedia |
| `GET /api/models` | model chat dari `CHAT_MODELS` + `available`/`reason` (Claude: ada API key; Ollama: server jalan & model sudah di-pull, dicek via `/api/tags`) |
| `GET /api/chats` | daftar riwayat `{id, title, updated_at, messages}` (terbaru dulu) |
| `GET /api/chats/<id>` | satu percakapan: `messages[]` (role, text, sources, usage, model) + `refs` + `pending` (jawaban yang masih dibuat) |
| `DELETE /api/chats/<id>` | hapus percakapan (DB + memori) |
| `POST /api/add` | `{text}` (link bebas, maks. 50) → `202` + job `{id, done, items[]}`; diproses di thread latar belakang |
| `GET /api/jobs/<id>` | progres job; tiap item: `stage` = queued · resolve · download · transcribe · ocr · summarize · done · exists · partial · error, plus `message`, `title` |
| `GET /api/pending` | item `status != processed` (mis. unduhan gagal) + `running` bila sedang diproses |
| `POST /api/retry` | `{shortcodes}` → job baru yang melanjutkan item dari tahap terakhirnya (item yang sedang berjalan ditolak) |
| `GET /api/instagram`, `POST /api/instagram/login` | status sesi (`sessionid` di `cookies.txt`) + jalankan `login.py` (jendela Chromium di komputer ini) |
| `GET /*` | `frontend/dist` (SPA) |

- **Riwayat percakapan** tersimpan di tabel `chats` (judul = pertanyaan pertama, `refs`
  = pemetaan `R12` → reel milik percakapan itu) dan `chat_messages` (teks, sumber, usage).
  Satu tanya-jawab disimpan setelah jawabannya selesai; jawaban yang gagal tidak tersimpan.
- Percakapan aktif ada di memori (`_sessions`, satu `Librarian` per id) dengan riwayat
  lengkap termasuk blok thinking. Bila id tidak ada di memori (server restart, percakapan
  lama dibuka), `_get_session()` memulihkannya dari DB: `build_library(refs)` memberi item
  lama nomor `R` yang sama (item baru → nomor lanjutan), dan riwayat dikirim **sebagai teks
  saja**. Alasannya: tanda tangan blok thinking mengikat system prompt asal; begitu
  perpustakaan berubah, mengirim ulang blok itu ditolak (400) pada akun yang menerapkan
  *preserved thinking*. Membuang semua blok thinking adalah pemulihan resmi dan aman.
  Terbukti: percakapan dilanjutkan setelah restart tanpa error, konteks tetap terjaga.
- **Jawaban tidak hilang bila browser terputus**: `POST /api/chat` menjalankan model di
  thread `_answer()` yang menulis ke objek `_Turn`; stream SSE hanya menontonnya. Tab
  di-refresh/dibekukan/ditutup tidak menghentikan jawaban — tetap selesai & tersimpan.
  `GET /api/chats/<id>` menyertakan `pending {question, text}` selama jawaban dibuat, dan
  frontend memantaunya sampai selesai. Model tidak diganti selama percakapan masih menjawab.
- **Pilihan model**: `POST /api/chat` menerima `model`. `_get_session(cid, model)` membuat
  ulang Librarian dari riwayat DB bila model berganti di tengah percakapan (riwayat teks
  berlaku untuk semua jenis). `ask.Librarian` (semua model Claude, mode penuh/pencarian)
  dan `ollama_chat.OllamaLibrarian` punya antarmuka yang sama (`stream`, `answer`,
  `cited`, `usage`, `refs`) dan memakai penomoran `R` yang sama (`ask.numbered_items`),
  jadi rujukan, riwayat, dan tampilan tidak membedakan model. Instruksinya meminta model mengabaikan persona lain — terbukti
  menimpa system prompt "Kimi K3" bawaan treyleo16. `chat_messages.model` mencatat model
  yang menjawab.
- **Balas teks yang diblok**: kutipan dikirim sebagai blockquote markdown di depan pertanyaan
  (`> kutipan\n\npertanyaan`) — tanpa field/endpoint baru, ikut tersimpan di `chat_messages`,
  dan dipisah lagi oleh `splitQuote()` saat ditampilkan. Nomor rujukan dirender lewat CSS
  (`.cite::before { content: attr(data-n) }`) agar tidak ikut tersalin ke kutipan.
- Satu percakapan hanya memproses satu pertanyaan sekaligus. Frontend mengingat id
  percakapan terakhir di `localStorage` (`chatId`).
- Job "tambah link" juga disimpan di memori server (`_jobs`) dan hilang saat restart;
  item yang sudah masuk DB tetap aman dan bisa dilanjutkan dengan `python pipeline.py`.
- Frontend: `App` (state per tab, cache daftar reel, pemantau beberapa job tambah link) ·
  `Toolbar` (cari, materi belajar, kategori, + Tambah) · `ReelGrid` (kartu + highlight) ·
  `ReelDetail` (video/slide, ringkasan, tab teks) · `ChatPanel` (stream SSE via `fetch`,
  rujukan nomor catatan kaki, pilihan model berkelompok Claude/Ollama, riwayat, balas teks
  yang diblok, lebar bisa diseret, lanjutkan jawaban yang masih dibuat server) ·
  `AddDialog` (tempel link, progres per link, ↻ Coba lagi, item "belum selesai", Login
  Instagram) · `ErrorBoundary` (error di satu panel tidak mengosongkan halaman) ·
  `storage.js` (`usePersistentState`). Tema terang/gelap mengikuti sistem.

## Batasan & risiko yang diketahui

- **API internal Instagram** (graphql, media info) tidak resmi dan bisa berubah kapan saja;
  kalau `collect.py`/`download_slides()` tiba-tiba gagal, regex atau endpoint perlu dicek ulang.
- **Sesi Instagram habis** (terjadi 2026-10-19): `cookies.txt` kehilangan `sessionid`, API
  media mengalihkan ke halaman login (HTML) sehingga parser JSON gagal ("Expecting value").
  Kini postingan publik diunduh tanpa login (lihat tabel keputusan). Login hanya untuk
  postingan privat: terdeteksi (`InstagramLoginRequired`, `instagram_logged_in()`), pengguna
  login lewat `login.py` / tombol web. Selama belum login, `ensure_cookies()` mengekspor
  ulang paling sering tiap 30 menit (tidak membuka Chromium di setiap penambahan link).
  Sisa `video.*` dari yt-dlp yang gagal di tengah carousel dibuang sebelum slide diunduh.
- **Keadaan tampilan** disimpan di `sessionStorage` (per tab: filter, panel, scroll, draf,
  cache `/api/reels` & `/api/status`) dan `localStorage` (model, lebar chat, id job tambah
  link), lewat `frontend/src/storage.js`.
- **Konteks tanya jawab mode penuh**: ±1.100 token per item (250.638 token / 224 item),
  sehingga konteks 1 juta token penuh di sekitar **900 item** — dan biaya pertanyaan
  pertama naik seiring ukuran. Menjelang itu, pindahkan model ke mode pencarian
  (`"mode": "search"` di `CHAT_MODELS`) atau tambahkan pencarian semantik (embedding).
  Haiku 4.5 (200K) sudah memakai mode pencarian.
- **Mode pencarian** hanya membaca item yang ditemukan FTS (kata kunci); item relevan yang
  memakai kata berbeda bisa terlewat. Katalog semua judul membantu model menyebutnya.
- **RAM 8 GB**: Chrome, Ollama, Whisper (GPU) dan Chromium untuk cookies bersaing memori;
  Claude Code pernah menghentikan server latar karena memori hampir habis. Jalankan
  `library.py` dari terminal sendiri.
- Server dirancang untuk **pemakaian lokal satu orang** (`127.0.0.1`, tanpa autentikasi).

## Ide berikutnya

- [x] Otomatiskan OCR dengan Claude API (vision) di `ocr.py`.
- [x] Satu perintah `pipeline.py` yang menjalankan download → process → ocr → summarize.
- [x] Tambah materi dari link manual (web "+ Tambah" dan `add.py`), termasuk TikTok.
- [x] Riwayat percakapan, balas teks yang diblok, pilihan model (Claude & Ollama).
- [x] Coba lagi unduhan yang gagal; unduh postingan Instagram publik tanpa login.
- [x] Halaman tidak ter-reset saat tab dibuka ulang; jawaban AI tetap selesai di server.
- [ ] Memori jangka panjang lintas percakapan (profil belajar, ringkasan percakapan lama,
  status reel "sudah ditonton").
- [ ] Unggah file video dari laptop (bukan link).
- [ ] Uji slideshow TikTok `/photo/` dengan postingan nyata (kode ada, belum teruji).
- [ ] Tombol "sembunyikan/hapus item" di web untuk membersihkan meme.
- [ ] Catatan pribadi / tandai "sudah dipelajari" per item.
