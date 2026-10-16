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
- **Tanya AI**: tanya apa saja tentang isi perpustakaan, misalnya
  *"aku mau belajar machine learning dari nol, reel mana yang harus kutonton dulu?"*.
  Rujukan di jawaban (berlabel judul reel) bisa diklik untuk membuka reel-nya.
  "Percakapan baru" memulai ulang konteks.

Tanya jawab juga bisa dari terminal:

```powershell
.\.venv\Scripts\python.exe ask.py                       # interaktif
.\.venv\Scripts\python.exe ask.py "tool AI apa saja yang pernah direkomendasikan?"
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

Link yang sudah ada di perpustakaan dilewati. Perkiraan waktu ±30 detik untuk video
pendek, lebih lama untuk video panjang (transkrip berjalan di GPU).

### B. Dari DM Instagram (banyak sekaligus)

```powershell
.\.venv\Scripts\python.exe collect.py    # login (sekali) → buka DM → Mulai Rekam → scroll ke atas → tutup
.\.venv\Scripts\python.exe pipeline.py   # unduh → transkrip → OCR → katalog untuk semua item baru
```

`pipeline.py` sama dengan menjalankan tahap-tahapnya satu per satu, yang juga bisa
dilakukan bila perlu (masing-masing punya opsi `--limit N` untuk mencoba sedikit dulu):
`download.py` → `process.py` → `ocr.py auto` → `summarize.py`.

Setelah menambah materi, klik "Percakapan baru" di panel Tanya AI supaya item baru
ikut terbaca. Server tidak perlu di-restart.

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
| Pertanyaan pertama (atau setelah jeda > 5 menit) | ±$0,70 — seluruh perpustakaan (±139 ribu token) ditulis ke cache |
| Pertanyaan berikutnya dalam 5 menit | ±$0,04 — perpustakaan dibaca dari cache |

Tips hemat: ajukan pertanyaan-pertanyaan secara beruntun dalam satu sesi, karena
cache hanya bertahan ±5 menit sejak terakhir dipakai.

Pemakaian token tiap jawaban ditampilkan di bawah jawaban.

## Masalah umum

| Gejala | Solusi |
|---|---|
| `download.py`: "GAGAL ekspor cookies" | Tutup `collect.py` / jendela Chromium yang memakai `browser_profile`. |
| Semua unduhan tiba-tiba gagal | Sesi Instagram habis. Jalankan `collect.py`, login ulang, tutup, lalu ulangi. |
| `process.py`: `cublas64_12.dll` tidak ditemukan | Pasang ulang paket `nvidia-*-cu12` dari `requirements.txt`. |
| Web: "Frontend belum di-build" | `cd frontend && npm install && npm run build`. |
| Panel Tanya AI: "API key belum diatur" | Periksa `.env`, lalu restart `library.py`. |
| Tambah link: "Gagal saat mengunduh" | Video privat/dihapus, atau sesi Instagram habis (lihat baris di atas). Link YouTube/TikTok: pastikan link video satuan, bukan playlist. |
| TikTok: "HTTP Error 403: Forbidden" | TikTok sesekali memblokir akses beruntun. Sudah dicoba ulang otomatis; kalau tetap gagal, tunggu beberapa menit lalu tambahkan lagi. |
| TikTok: "Your IP address is blocked from accessing this post" | Postingan dibatasi wilayah oleh pembuatnya; tidak bisa diambil dari Indonesia. |
| TikTok: "Link TikTok tidak berlaku lagi" | Link pendek mengarah ke beranda TikTok: postingannya sudah dihapus atau privat. |
| Tambah link: status "Sebagian" | Item tersimpan tapi belum diringkas (biasanya API key belum diatur). Jalankan `python pipeline.py` setelah memperbaikinya. |

## Data rahasia

`.env` (API key), `cookies.txt`, dan `browser_profile/` (sesi login Instagram) memberi
akses ke akunmu. Jangan dibagikan, diunggah, atau dimasukkan ke repositori publik.
