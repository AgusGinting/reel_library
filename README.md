# Perpustakaan Reel

Perpustakaan pribadi dari reel & postingan Instagram yang kamu terima lewat DM.
Setiap video ditranskrip, teks di layarnya dibaca, lalu dikatalogkan oleh Claude
(judul, ringkasan, poin penting, topik, kategori, materi belajar atau bukan).
Hasilnya bisa dicari dan **ditanyai** lewat web lokal, dan AI-nya selalu menyebut
reel sumber jawabannya.

Cara kerja dan alasan desainnya ada di [ARCHITECTURE.md](ARCHITECTURE.md).

## Kebutuhan

- Windows dengan Python 3.11 (di `.venv`) dan Node.js 22+
- `ffmpeg` di PATH
- GPU NVIDIA (opsional; tanpa GPU transkrip tetap jalan di CPU, lebih lambat)
- API key Claude (untuk katalog & tanya jawab)

## Instalasi (sekali saja)

```powershell
# Python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

# Frontend
cd frontend
npm install
npm run build
cd ..
```

Buat file `.env` di folder proyek berisi API key (jangan dibagikan):

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Memakai perpustakaan

```powershell
.\.venv\Scripts\python.exe library.py
```

Buka **http://127.0.0.1:5000**.

- **Cari**: kata kunci dicari di caption, transkrip, teks layar, dan ringkasan.
- **Filter**: *Materi belajar / Semua / Lainnya* dan per kategori.
- **Klik kartu**: putar video atau geser slide, baca ringkasan, transkrip, dan teks layar.
- **+ Tambah**: tambah materi dari link (lihat di bawah).
- **Tidak ter-reset saat pindah tab**: pencarian, filter, panel yang terbuka, reel yang
  sedang dilihat, posisi scroll, draf pertanyaan/kutipan, dan progres "Tambah materi"
  dipulihkan saat tab dibuka lagi (Chrome sering memuat ulang tab latar belakang bila RAM
  menipis). Daftar reel tampil dari cache dulu lalu diperbarui. Jawaban AI yang sedang
  dibuat tetap diselesaikan server dan muncul lagi saat tab dibuka.
- **Tanya AI**: tanya apa saja tentang isi perpustakaan, misalnya
  *"aku mau belajar machine learning dari nol, reel mana yang harus kutonton dulu?"*.
  Rujukan di jawaban berupa nomor kecil (¹ ²) — arahkan kursor untuk melihat judul,
  klik untuk membuka reel-nya; daftar "Sumber" di bawah jawaban memakai nomor yang sama.
- **Pilih model AI** (di atas kotak ketik, pilihan diingat browser):

  | Model | Biaya per pertanyaan* | Cara membaca perpustakaan |
  |---|---|---|
  | Claude Haiku 4.5 | ±$0,02 | mode pencarian (konteks 200K hampir penuh oleh perpustakaan) — tercepat |
  | Claude Haiku 5.5 | ±$0,16 pertama, ±$0,015 berikutnya | seluruh perpustakaan (konteks 1M) — paling hemat untuk mode penuh |
  | Claude Sonnet 5.5 (bawaan) | ±$0,63 pertama, ±$0,03 berikutnya | seluruh perpustakaan |
  | Claude Opus 5.5 | ±$1,25 pertama, ±$0,05 berikutnya | seluruh perpustakaan |
  | Claude Fable 5.1 | ±$3,10 pertama, ±$0,06 berikutnya | seluruh perpustakaan — paling cerdas |
  | Gemma 4 31B (`gemma4:31b-cloud`) | gratis (Ollama cloud) | mode pencarian; ±3 detik per jawaban |
  | treyleo16/kimi-k3 | gratis (Ollama cloud) | sama dengan Gemma — model ini sebenarnya Gemma 4 31B berlabel "Kimi K3" |

  \*Untuk ±250 ribu token perpustakaan (224 item). "Pertama" = pertanyaan pertama atau
  setelah jeda > 5 menit (perpustakaan ditulis ke cache); "berikutnya" = dibaca dari cache.
  Mode pencarian = daftar semua judul + detail ±15 item paling relevan dengan pertanyaan.

  Model boleh diganti di tengah percakapan; tiap jawaban mencatat model yang menjawab.
  Model Ollama butuh aplikasi Ollama berjalan, login (`ollama signin`), dan sudah
  di-pull (`ollama pull gemma4:31b-cloud`). Tambah model lain di `CHAT_MODELS` (`config.py`).
- **Balas bagian tertentu**: blok (sorot) teks di jawaban atau pesanmu → klik **↩ Balas**
  → tulis pertanyaan. Kutipan dikirim ke AI sebagai konteks dan tampil di gelembung pesanmu.
  **Esc** atau **×** membatalkan kutipan.
- **Riwayat percakapan**: semua tanya jawab tersimpan di `library.db`. Tombol
  **Riwayat** menampilkan percakapan lama (buka untuk melanjutkan, × untuk menghapus);
  **Percakapan baru** memulai topik baru. Percakapan yang terakhir dibuka muncul lagi
  setelah halaman di-refresh atau server di-restart.

Tanya jawab juga bisa dari terminal:

```powershell
.\.venv\Scripts\python.exe ask.py                       # interaktif
.\.venv\Scripts\python.exe ask.py "tool AI apa saja yang pernah direkomendasikan?"
.\.venv\Scripts\python.exe ask.py --model claude-haiku-4-5 "reel tentang SQL?"   # pilih model Claude
```

## Menambah materi baru

### A. Dari link (paling mudah)

Di web, klik **+ Tambah**, tempel satu atau beberapa link (satu per baris), lalu
**Tambahkan**. Setiap link diunduh, ditranskrip, dibaca teks layarnya, lalu diringkas
AI. Progresnya tampil per link (Mengunduh → Transkrip suara → Membaca teks layar →
Meringkas → Selesai). Jendelanya boleh ditutup; galeri bertambah sendiri saat selesai.

Dari terminal:

```powershell
.\.venv\Scripts\python.exe add.py https://www.instagram.com/reel/XXXXXXXXXXX/
.\.venv\Scripts\python.exe add.py <link1> <link2> ...
.\.venv\Scripts\python.exe add.py --file links.txt
```

Link yang didukung:

| Sumber | Yang bisa ditambahkan |
|---|---|
| Instagram | reel, postingan video, postingan foto/carousel |
| TikTok | video & slideshow foto, termasuk link pendek dari tombol *Bagikan* (`vt.tiktok.com/…`, `vm.tiktok.com/…`) |
| YouTube & situs lain yang didukung yt-dlp | satu video per link (bukan playlist) |

Link yang sudah ada di perpustakaan dilewati.

**Kalau gagal:** item yang gagal menampilkan tombol **↻ Coba lagi** (dan **↻ Coba lagi
semua** bila lebih dari satu). Item yang gagal di sesi sebelumnya tetap muncul di bagian
**"Belum selesai dari sebelumnya"**, walau server sudah di-restart.

Postingan Instagram **publik** (reel, foto, carousel) diunduh **tanpa login**. Login hanya
diperlukan untuk postingan privat/dibatasi: bila itu penyebabnya, muncul tombol
**Login Instagram** — jendela Chromium terbuka di halaman login, setelah kamu login
jendelanya tertutup sendiri — lalu klik Coba lagi. Dari terminal: `python login.py`,
lalu `python pipeline.py`. Perkiraan waktu ±30 detik untuk video
pendek, lebih lama untuk video panjang (transkrip berjalan di GPU).

### B. Dari DM Instagram (banyak sekaligus)

```powershell
.\.venv\Scripts\python.exe collect.py    # login (sekali) → buka DM → Mulai Rekam → scroll ke atas → tutup
.\.venv\Scripts\python.exe pipeline.py   # unduh → transkrip → OCR → katalog untuk semua item baru
```

`pipeline.py` sama dengan menjalankan tahap-tahapnya satu per satu, yang juga bisa
dilakukan bila perlu (masing-masing punya opsi `--limit N` untuk mencoba sedikit dulu):
`download.py` → `process.py` → `ocr.py auto` → `summarize.py`.

Item baru langsung ikut terbaca di percakapan berikutnya. Server tidak perlu di-restart.

## Mengubah tampilan web

```powershell
.\.venv\Scripts\python.exe library.py      # terminal 1 (API)
cd frontend; npm run dev                   # terminal 2 → http://localhost:5173
```

Perubahan di `frontend/src` langsung terlihat. Setelah selesai, `npm run build`
agar ikut tersaji di port 5000.

## Biaya Claude API

| Kegiatan | Perkiraan |
|---|---|
| Katalog 125 item (`summarize.py`) | ±$1,89 (sudah dijalankan) |
| Menambah 1 materi | ±$0,02 (katalog) + ±$0,01–0,10 bila perlu OCR teks layar |
| Tanya AI dengan Gemma 4 31B / treyleo16 | gratis (memakai jatah paket gratis Ollama, ±14 ribu token per pertanyaan) |
| Tanya AI dengan Claude | lihat tabel model di atas (Haiku ±$0,02 … Fable ±$3,10 untuk pertanyaan pertama) |

Tips hemat: ajukan pertanyaan-pertanyaan secara beruntun dalam satu sesi, karena
cache hanya bertahan ±5 menit sejak terakhir dipakai.

Pemakaian token tiap jawaban ditampilkan di bawah jawaban.

## Masalah umum

| Gejala | Solusi |
|---|---|
| `download.py`: "GAGAL ekspor cookies" | Tutup `collect.py` / jendela Chromium yang memakai `browser_profile`. |
| "…tidak bisa dibuka tanpa login (privat/dibatasi)…" | Klik **Login Instagram** di jendela Tambah materi (atau `python login.py`), login, lalu **↻ Coba lagi**. |
| "Expecting value: line 1 column 1" (versi lama) | Versi lama mengunduh foto/carousel lewat API yang butuh login; saat sesi habis Instagram membalas halaman login. Kini postingan publik diunduh tanpa login — cukup **↻ Coba lagi**. |
| `process.py`: `cublas64_12.dll` tidak ditemukan | Pasang ulang paket `nvidia-*-cu12` dari `requirements.txt`. |
| Web: "Frontend belum di-build" | `cd frontend && npm install && npm run build`. |
| Panel Tanya AI: "API key belum diatur" | Periksa `.env`, lalu restart `library.py`. Atau pilih model Gemma (gratis). |
| Model Ollama "(tidak tersedia)" | Buka aplikasi Ollama; jalankan `ollama signin` dan `ollama pull <nama model>`, lalu buka ulang panel chat. |
| Ollama: "402 Payment Required" | Model itu tidak termasuk paket gratis Ollama (mis. `kimi-k3:cloud` asli). Pakai `gemma4:31b-cloud` atau isi kredit di ollama.com. |
| Tambah link: "Gagal saat mengunduh" | Video privat/dihapus, atau sesi Instagram habis (lihat baris di atas). Link YouTube/TikTok: pastikan link video satuan, bukan playlist. |
| TikTok: "HTTP Error 403: Forbidden" | TikTok sesekali memblokir akses beruntun. Sudah dicoba ulang otomatis; kalau tetap gagal, tunggu beberapa menit lalu tambahkan lagi. |
| TikTok: "Your IP address is blocked from accessing this post" | Postingan dibatasi wilayah oleh pembuatnya; tidak bisa diambil dari Indonesia. |
| TikTok: "Link TikTok tidak berlaku lagi" | Link pendek mengarah ke beranda TikTok: postingannya sudah dihapus atau privat. |
| Tambah link: status "Sebagian" | Item tersimpan tapi belum diringkas (biasanya API key belum diatur). Jalankan `python pipeline.py` setelah memperbaikinya. |

## Data rahasia

`.env` (API key), `cookies.txt`, dan `browser_profile/` (sesi login Instagram) memberi
akses ke akunmu. Jangan dibagikan, diunggah, atau dimasukkan ke repositori publik.
