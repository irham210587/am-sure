# Telusur

Bot pencarian real-time tanpa database. Setiap kali kamu bertanya, bot menelusuri web saat
itu juga, lalu menjawab dengan paragraf yang mengalir. Pencariannya berjalan di balik layar:
tidak ada daftar sumber, tidak ada tautan, tidak ada langkah yang ditampilkan.

Tidak ada vector database, tidak ada Postgres, tidak ada Redis. Server sama sekali tidak
menyimpan data. Satu-satunya yang menyimpan riwayat adalah browser kamu, di `localStorage`.

---

## Cara kerjanya

```
Browser  ──POST /api/chat {pertanyaan, riwayat}──▶  FastAPI
                                                      │
                                       0. kalau pertanyaan menyebut tempat dan tombol
                                          Lokasi aktif: koordinat jadi nama daerah,
                                          lalu tempat dalam radius 2 km dicari
                                       1. tulis ulang pertanyaan jadi query mandiri
                                       2. Tavily: cari 5 halaman web
                                       3. susun hasilnya jadi bahan internal untuk model
                                       4. model menulis jawaban naratif dari bahan itu
                                       5. rapikan keluarannya, kirim lewat SSE token demi token
                                                      │
Browser  ◀──────────── jawaban mengalir sebagai paragraf ┘
```

Empat hal yang membuat jawabannya akurat, bukan sekadar lancar:

1. **Query rewriting.** Pertanyaan lanjutan seperti "kalau yang kedua?" diubah dulu jadi
   query pencarian yang berdiri sendiri. Tanpa langkah ini, pencariannya jadi sampah.
2. **Grounding ketat.** System prompt melarang model menjawab di luar bahan yang dikumpulkan.
   Kalau bahan tidak memuat jawabannya, model disuruh bilang informasinya belum tersedia.
3. **Tanggal hari ini disuntik ke prompt**, supaya "terbaru" dan "minggu ini" punya acuan.
4. **Keluaran disaring sebelum tampil.** Jawaban dibersihkan dari tautan, nama domain, sitasi,
   dan penanda daftar. Yang sampai ke layar hanya paragraf.

---

## Daftar layanan, kunci API, dan fitur

Bagian ini menjawab pertanyaan "sebenarnya bot ini memakai apa saja". Semua nama variabel di
bawah sama persis dengan yang dibaca kode, jadi bisa dipakai sebagai daftar periksa saat
mengisi `.env` maupun dashboard Vercel.

### A. Kunci penyedia teks dan gambar

| Variabel | Layanan | Gunanya | Wajib? |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | Tokenomix, DeepSeek, atau gateway lain | Menulis jawaban, menulis ulang pertanyaan lanjutan, dan membaca gambar | **Ya** |
| `DEEPSEEK_BASE_URL` | alamat API penyedia | Ke server mana permintaan dikirim | Tidak, bawaan `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | nama model | Model yang menulis jawaban | Tidak, bawaan `deepseek-chat` |
| `VISION_MODEL` | nama model | Model yang mengubah gambar jadi kata kunci | Tidak, bawaan `deepseek-v4-flash-vision-exp` |

Kunci gambar memakai kunci yang sama dengan teks, hanya modelnya berbeda. Jadi tombol Gambar
tidak butuh pendaftaran baru. Satu catatan: kalau penyediamu tidak melayani model vision,
tombol Gambar akan gagal, dan `VISION_MODEL` perlu diisi nama model yang memang ada di sana.

### B. Kunci pencarian web

| Variabel | Layanan | Gunanya | Wajib? |
|---|---|---|---|
| `TAVILY_API_KEY` | Tavily | Mencari lima halaman web untuk setiap pertanyaan | **Ya** |

Tanpa kunci ini bot tidak punya bahan untuk dijawab, jadi setiap pertanyaan akan gagal dengan
pesan kuota atau kunci.

### C. Kunci suara (opsional)

| Variabel | Layanan | Gunanya | Wajib? |
|---|---|---|---|
| `STT_BASE_URL` | Groq atau penyedia lain yang kompatibel OpenAI | Alamat layanan transkripsi | Tidak |
| `STT_API_KEY` | Groq | Kunci transkripsi | Tidak |
| `STT_MODEL` | nama model | Model transkripsi | Tidak, bawaan `whisper-large-v3-turbo` |

Ketiganya hanya dipakai tombol Suara dan Bicara. Kalau kosong, kedua tombol itu memberi pesan
bahwa fiturnya belum dikonfigurasi, dan sisa bot tetap jalan normal.

### D. Layanan yang tidak butuh kunci sama sekali

| Layanan | Gunanya | Dipakai oleh |
|---|---|---|
| Nominatim (OpenStreetMap) | Mengubah koordinat jadi nama daerah | Tombol Lokasi |
| Photon (Komoot) | Mencari tempat dalam radius 2 km | Tombol Lokasi |
| Google Fonts | Huruf Newsreader dan JetBrains Mono | Browser, langsung dari CDN |
| Vercel | Hosting fungsi Python dan berkas statis | Produksi |

Dua layanan peta itu terbuka tanpa pendaftaran. Karena itu fitur lokasi bisa dipakai tanpa
menambah satu pun kunci.

### E. Pengaturan yang bukan kunci

| Variabel | Gunanya | Bawaan |
|---|---|---|
| `APP_ACCESS_KEY` | Kalau diisi, `/api/chat`, `/api/vision`, dan `/api/transcribe` wajib membawa header `X-Access-Key` | Kosong, artinya penjaga mati |
| `GEO_USER_AGENT` | Identitas yang dikirim ke Nominatim, diminta aturan layanannya | `AmSure/1.0 (personal search bot)` |
| `VERCEL_GIT_COMMIT_SHA` | Diisi Vercel sendiri, dibaca `/api/health` sebagai penanda build | Kosong di komputer sendiri |

### F. Fitur dan apa yang dibutuhkannya

| Fitur | Butuh | Kalau tidak tersedia |
|---|---|---|
| Jawaban naratif dari web | `DEEPSEEK_API_KEY`, `TAVILY_API_KEY` | Bot tidak bisa menjawab |
| Riwayat tetap ada setelah refresh | `localStorage` di browser | Tidak ada layanan yang terlibat |
| Jawaban mengalir token demi token | SSE dari FastAPI | Jawaban tetap muncul, hanya sekaligus di akhir |
| Tanya lanjutan yang nyambung | Satu panggilan LLM tambahan | Dianggap pertanyaan baru |
| Unggah gambar | `DEEPSEEK_API_KEY` + model vision | Tombol Gambar gagal |
| Unggah audio | `STT_BASE_URL`, `STT_API_KEY`, `STT_MODEL` | Tombol Suara menampilkan pesan |
| Bicara langsung | Kunci suara + mikrofon browser | Tombol Bicara menampilkan pesan |
| Tempat terdekat | Izin lokasi browser + Nominatim + Photon | Tombol Lokasi tidak bisa dipakai |
| Halaman terkunci | `APP_ACCESS_KEY` | Siapa pun yang punya tautan bisa memakai kuotamu |

### G. Endpoint dan penjaganya

| Endpoint | Fungsi | Perlu kunci akses? |
|---|---|---|
| `GET /api/health` | Status konfigurasi, tanpa membocorkan nilai kunci | Tidak |
| `POST /api/chat` | Tanya jawab, balasan SSE | Ya |
| `POST /api/vision` | Gambar jadi kata kunci pencarian | Ya |
| `POST /api/transcribe` | Audio jadi teks | Ya |
| `GET /` dan berkas statis | Halaman antarmuka | Tidak |
| `GET /api/docs` | Dokumentasi API otomatis dari FastAPI | Tidak |

Penjaga hanya aktif kalau `APP_ACCESS_KEY` diisi. Di komputer sendiri biasanya dikosongkan,
di Vercel sebaiknya diisi.

### H. Apa yang dipakai per satu pertanyaan

| Jenis pertanyaan | Panggilan berbayar |
|---|---|
| Pertanyaan pertama | 1 pencarian Tavily + 1 panggilan model |
| Pertanyaan lanjutan | 1 pencarian Tavily + 2 panggilan model |
| Pertanyaan tempat (Lokasi aktif) | Sama seperti di atas, ditambah 2 permintaan peta gratis |
| Gambar | 1 panggilan model vision, lalu dihitung seperti pertanyaan biasa |
| Suara atau Bicara | 1 transkripsi, lalu dihitung seperti pertanyaan biasa |

Yang perlu diingat soal biaya: Tavily punya kuota gratis 1.000 pencarian per bulan, Groq punya
paket gratis untuk transkripsi, dan layanan peta tidak berbayar. Yang benar-benar menagih per
pemakaian hanya penyedia model teks.

Kesimpulannya, untuk menjalankan bot ini cukup **dua kunci**: satu untuk model, satu untuk
pencarian. Kunci ketiga hanya perlu kalau ingin memakai suara.

---

## Instalasi

Ikuti berurutan. Setiap langkah punya cara memeriksa bahwa langkah itu berhasil.

Butuh: macOS atau Linux, koneksi internet, dan dua API key wajib (diambil di Langkah 4).
Kunci ketiga untuk suara sifatnya opsional.
Tidak perlu MAMP, tidak perlu Node, tidak perlu Docker.

### Langkah 1 — Pastikan Python 3.10 atau lebih baru ada

```bash
python3 -V
```

Yang benar, keluarannya seperti ini atau lebih tinggi:

```
Python 3.11.6
```

Kalau yang muncul `command not found: python3`, atau versinya di bawah 3.10:

```bash
brew install python
```

Kalau `brew` juga belum ada, install Homebrew dulu dari <https://brew.sh>, lalu ulangi.

### Langkah 2 — Masuk ke folder proyek

```bash
cd /Applications/MAMP/htdocs/test-claude-code
```

Perintah `ls` seharusnya menampilkan `main.py`, `brain.py`, `requirements.txt`, dan `frontend`.

### Langkah 3 — Buat virtual environment dan pasang dependency

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Prompt terminal akan berubah jadi berawalan `(.venv)`. Itu tandanya venv aktif.

Periksa hasilnya:

```bash
python -c "import fastapi, openai, tavily; print('dependency OK')"
```

Harus keluar `dependency OK`.

> Kalau `python3 -m venv` gagal dengan pesan soal `ensurepip`, jalankan
> `xcode-select --install`, lalu ulangi Langkah 3.

### Langkah 4 — Ambil dua API key

Daftar lengkap semua kunci, termasuk yang opsional, ada di bagian **Daftar layanan, kunci API,
dan fitur** di atas. Di langkah ini kita ambil dua yang wajib dulu.

Bot butuh dua layanan. Keduanya punya halaman pendaftaran gratis.

**4a. DeepSeek** — mesin yang merangkum jawaban.

1. Buka <https://platform.deepseek.com>
2. Daftar, lalu buka menu **API keys**
3. Klik **Create new API key**
4. Salin kuncinya (bentuknya `sk-xxxxxxxx...`)

Kunci ini hanya ditampilkan sekali. Simpan dulu di catatan sementara.

**4b. Tavily** — mesin pencari yang membuka halaman web.

1. Buka <https://app.tavily.com>
2. Daftar dengan Google atau email
3. Kunci langsung tersedia di halaman dashboard (bentuknya `tvly-xxxxxxxx...`)

Kuota gratisnya 1.000 pencarian per bulan, cukup untuk pemakaian pribadi.

### Langkah 5 — Isi file .env

```bash
cp .env.example .env
```

Buka `.env` dengan editor apa pun. Ada dua pilihan, pakai salah satu.

**Pilihan A — DeepSeek resmi.** Ganti dua baris ini:

```env
DEEPSEEK_API_KEY=sk-kunci-kamu-yang-asli
TAVILY_API_KEY=tvly-kunci-kamu-yang-asli
```

**Pilihan B — gateway OpenAI-compatible, misalnya Tokenomix.** Beri tanda `#` pada blok
Pilihan A, lalu isi blok Pilihan B seperti ini:

```env
DEEPSEEK_API_KEY=sk-tkx-kunci-dari-dashboard
DEEPSEEK_BASE_URL=https://api.tokenomixai.com/v1
DEEPSEEK_MODEL=glm-5.1
TAVILY_API_KEY=tvly-kunci-kamu-yang-asli
```

Sesudah mengisi `.env`, uji koneksinya dulu tanpa membuka browser:

```bash
.venv/bin/python check_provider.py
```

Kalau berhasil, skrip itu mencetak satu balasan model. Kalau gagal dengan pesan soal
model, lihat nama yang tersedia:

```bash
.venv/bin/python check_provider.py --models
```

Dua hal yang paling sering salah di Pilihan B:

- `DEEPSEEK_BASE_URL` harus berakhiran `/v1`. Tanpa itu, permintaan mendarat di alamat
  yang salah dan dibalas 404.
- `DEEPSEEK_MODEL` harus persis sama dengan nama model di dashboard gateway. `glm-5.1`
  adalah salah satu yang tersedia di Tokenomix, tapi gateway juga melayani model lain
  seperti DeepSeek dan Kimi. Nama pastinya bisa dilihat lewat `check_provider.py --models`.

Simpan. Jangan tambahkan tanda kutip, jangan tambahkan spasi setelah `=`.

Periksa bahwa tidak ada placeholder tersisa (baris berawalan `#` diabaikan):

```bash
grep -cE '^[^#].*isi-di-sini' .env
```

Harus keluar `0`. Kalau keluar angka lain, masih ada nilai contoh yang belum diganti.

### Langkah 6 — Jalankan

```bash
uvicorn main:app --reload
```

Keluaran yang benar:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

Biarkan terminal ini terbuka. Server berhenti kalau kamu tekan `Ctrl+C`.

### Langkah 7 — Buka dan uji

Buka <http://127.0.0.1:8000> di browser.

Periksa dari terminal juga, di tab terminal baru:

```bash
curl -s http://127.0.0.1:8000/api/health
```

Jawaban yang benar:

```json
{"ok":true,"deepseek_key":true,"tavily_key":true,"model":"deepseek-chat"}
```

Kalau `ok` bernilai `false`, berarti salah satu kunci di `.env` belum terbaca. Hentikan
server dengan `Ctrl+C`, perbaiki `.env`, jalankan ulang.

Lalu di browser, ketik pertanyaan yang jawabannya berubah tiap hari, misalnya
`berapa harga bitcoin sekarang`. Dalam beberapa detik jawaban mulai mengalir sebagai paragraf,
tanpa daftar sumber dan tanpa tautan.

---

## Cara cepat: satu perintah

Kalau tidak mau mengetik Langkah 2 sampai 6 setiap kali, pakai skrip yang sudah disiapkan:

```bash
./run.sh
```

Skrip itu membuat venv kalau belum ada, memasang dependency kalau kurang, memeriksa `.env`,
lalu menyalakan server. Pada pemakaian pertama ia akan berhenti dan meminta kamu mengisi
`.env` dulu. Setelah itu, `./run.sh` saja sudah cukup.

Kalau `./run.sh` ditolak dengan `permission denied`:

```bash
chmod +x run.sh
./run.sh
```

Mau port lain karena 8000 sudah dipakai (misalnya oleh MAMP)?

```bash
PORT=8001 ./run.sh
```

---

## Deploy ke Vercel

Vercel menerima `main.py` sebagai entrypoint FastAPI secara langsung, jadi tidak perlu folder
`api/` atau konfigurasi routing tambahan. Folder `frontend/` otomatis diangkat ke CDN.

**1. Unggah ke GitHub.** Folder ini belum berupa repo git. Jalankan berurutan:

```bash
git init -b main
git add -A
git status --short      # pastikan .env TIDAK muncul di daftar ini
git commit -m "Bot pencarian tanpa database"
```

Lalu buat repo kosong di <https://github.com/new>, dan jalankan dua perintah `git remote add`
serta `git push` yang ditampilkan GitHub setelah repo dibuat. Kunci API tidak ikut terkirim
karena `.env` sudah tercantum di `.gitignore`.

**2. Impor proyek di Vercel.** Buka <https://vercel.com/new>, pilih repo tadi. Biarkan
framework preset terdeteksi otomatis; jangan diubah ke Next.js.

**3. Isi environment variables** di Project Settings, satu per satu:

| Nama | Nilai |
|---|---|
| `DEEPSEEK_API_KEY` | kunci dari Tokenomix atau DeepSeek |
| `DEEPSEEK_BASE_URL` | `https://api.tokenomixai.com/v1` |
| `DEEPSEEK_MODEL` | `glm-5.3` atau model lain yang tersedia |
| `TAVILY_API_KEY` | kunci Tavily |
| `APP_ACCESS_KEY` | kalimat rahasia buatanmu sendiri |

Tiga variabel berikut opsional, tapi tanpanya tombol Suara tidak berfungsi:

| Nama | Nilai |
|---|---|
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` |
| `STT_API_KEY` | kunci dari penyedia speech to text |
| `STT_MODEL` | `whisper-large-v3-turbo` |

`VISION_MODEL` juga bisa ditambahkan kalau ingin mengganti model pembaca gambar; kalau
dibiarkan kosong dipakai `deepseek-v4-flash-vision-exp`. Setelah menambah variabel apa pun,
lakukan redeploy supaya nilainya terbaca.

Baris terakhir itu penting. Tautan Vercel bersifat publik, sedangkan kunci LLM-mu berbayar.
Tanpa `APP_ACCESS_KEY`, siapa pun yang menemukan tautannya bisa memakai kuotamu.

Sebagai alternatif, Vercel punya **Deployment Protection** bawaan di Settings. Bedanya, cara
itu mewajibkan penonton punya akun Vercel dan login. Kunci akses lebih praktis kalau kamu
hanya ingin membagikan tautan ke beberapa orang tanpa memaksa mereka mendaftar. Keduanya bisa
dipakai bersamaan.

Kalau lebih suka terminal daripada dashboard, variabel yang sama bisa diisi lewat CLI. Membaca
nilai dari berkas mencegahnya tercatat di riwayat shell:

```bash
npx vercel env add DEEPSEEK_API_KEY production < ./secret.txt
npx vercel env add TAVILY_API_KEY production < ./secret.txt
npx vercel env add APP_ACCESS_KEY production < ./secret.txt
```

Satu jebakan yang perlu dihindari: `npx vercel env pull <berkas>` **menimpa seluruh isi berkas
yang ditunjuk**. Jangan arahkan ke `.env` milikmu, karena kunci Tokenomix dan Tavily yang sudah
bekerja akan hilang. Kalau perlu menarik variabel dari Vercel, pakai nama lain seperti
`.env.vercel`.

**4. Deploy.** `vercel.json` sudah menyetel region `sin1` (Singapura) dan `maxDuration` 300
detik, yaitu batas tertinggi paket Hobby. Angka itu ditulis eksplisit supaya tidak tertimpa
pengaturan dashboard yang lebih rendah.

**5. Uji.** Buka `https://nama-proyek.vercel.app`. Halaman akan meminta kunci akses; masukkan
nilai `APP_ACCESS_KEY` yang tadi dibuat. Kunci tersimpan di browser, jadi hanya diminta sekali.

Untuk memeriksa dari terminal:

```bash
curl -s https://nama-proyek.vercel.app/api/health
```

Balasan `{"ok":true,...,"access_required":true}` berarti konfigurasi terbaca. Permintaan ke
`/api/chat` tanpa header `X-Access-Key` akan dijawab `401`.

Permintaan pertama setelah lama menganggur bisa terasa lambat karena function bangun dari nol.
Itu normal di paket gratis.

Untuk memastikan aset statis benar-benar dilayani CDN dan bukan dari function:

```bash
curl -sSI https://nama-proyek.vercel.app/style.css | grep -iE 'x-vercel-cache|cache-control'
```

`x-vercel-cache: HIT` berarti berkas itu datang dari CDN. Kalau hasilnya kosong atau `MISS`,
halaman tetap berfungsi, hanya saja setiap permintaan aset ikut membangunkan function.

### Membangun ulang setelah mengubah variabel

Variabel environment hanya terbaca saat build baru, jadi menambah atau mengubahnya tidak
berpengaruh sampai kamu membangun ulang. Ada tiga cara, pilih yang paling nyaman.

**Lewat dashboard.** Buka proyek di Vercel, tab **Deployments**, klik tombol `⋯` di kanan
deployment paling atas, lalu pilih **Redeploy**. Setelah menyimpan variabel baru, Vercel
kadang juga menampilkan tombol Redeploy langsung di halaman itu.

**Lewat commit kosong.** Memicu build baru tanpa mengubah kode sama sekali:

```bash
git commit --allow-empty -m "Picu deploy ulang"
git push origin main
```

**Lewat CLI.**

```bash
npx vercel --prod
```

Setelah build selesai, pastikan hasilnya di `/api/health`. Ada dua penanda yang berguna:

- `"commit"` berisi tujuh huruf pertama commit yang sedang dipasang di produksi. Bandingkan
  dengan `git rev-parse --short HEAD` di komputermu. Kalau sama, build terbaru sudah live.
- `"stt_ready"` berubah dari `false` menjadi `true` setelah `STT_BASE_URL` dan `STT_API_KEY`
  terpasang di dashboard.

### Deploy lewat terminal, tanpa GitHub

Vercel CLI tidak perlu dipasang permanen; `npx` cukup:

```bash
npx vercel login
npx vercel link
npx vercel --prod
```

Perintah pertama membuka browser untuk masuk. `link` menghubungkan folder ini ke sebuah proyek,
`--prod` menerbitkannya. Isi dulu environment variable lewat dashboard atau `npx vercel env add`,
karena deploy tanpa kunci akan tetap berjalan tetapi setiap pertanyaan gagal.

## Troubleshooting

| Yang muncul | Artinya | Perbaikan |
|---|---|---|
| `command not found: uvicorn` | venv tidak aktif | `source .venv/bin/activate`, atau pakai `.venv/bin/uvicorn main:app --reload` |
| `ModuleNotFoundError: No module named 'fastapi'` | Dependency tidak terpasang di interpreter yang dipakai | `source .venv/bin/activate` lalu `pip install -r requirements.txt` |
| `[Errno 48] Address already in use` | Port 8000 sudah dipakai proses lain | `uvicorn main:app --reload --port 8001` |
| `DEEPSEEK_API_KEY belum di-set` | `.env` tidak ada atau kosong | Pastikan `.env` ada di folder yang sama dengan `main.py`, lalu restart server |
| `ok:false` di `/api/health` | Salah satu kunci tidak terbaca | Cek nama variabel di `.env` harus persis `DEEPSEEK_API_KEY` dan `TAVILY_API_KEY` |
| `AuthenticationError` atau `401` | Kunci salah atau sudah dicabut | Buat kunci baru di dashboard, ganti di `.env`, restart |
| `404` saat menjawab | `DEEPSEEK_BASE_URL` salah, biasanya kurang `/v1` | Samakan persis dengan base URL di dashboard gateway |
| Balasan 400 soal model | `DEEPSEEK_MODEL` tidak dikenali gateway | Salin nama model apa adanya dari dashboard gateway |
| `Insufficient Balance` atau `402` | Saldo akun DeepSeek belum diisi | Isi ulang di <https://platform.deepseek.com/top_up>. Tidak perlu restart |
| `Pencarian web gagal: 432` | Kuota gratis Tavily habis | Tunggu bulan berikutnya atau naikkan paket |
| Halaman terbuka tapi muncul "Server tidak merespons" | `uvicorn` sudah berhenti | Jalankan ulang Langkah 6 |
| Tampilan tanpa font yang benar | Google Fonts tidak terjangkau | Tidak fatal, teks tetap terbaca dengan font sistem |
| Jawaban bilang "informasi tidak ditemukan" | Sumber memang tidak memuat jawabannya | Ini perilaku yang benar. Coba pertanyaan lebih spesifik |

Untuk menghentikan server: `Ctrl+C` di terminal tempat `uvicorn` berjalan.

---

## Struktur

```
.
├── main.py               Endpoint HTTP dan streaming SSE
├── brain.py              Inti RAG: rewrite, search, prompt, saring keluaran
├── geo.py                Tempat sekitar: koordinat, jarak, OpenStreetMap
├── check_provider.py     Skrip uji koneksi ke penyedia LLM
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/test_brain.py   Tes untuk fungsi murni, tanpa jaringan
├── run.sh                Skrip sekali-jalan
├── requirements.txt
└── .env.example
```

Pemisahannya disengaja. `brain.py` tidak tahu apa-apa soal HTTP, jadi bisa dites dan dipakai
ulang oleh antarmuka lain. `main.py` hanya urusan transport.

---

## Tes

```bash
source .venv/bin/activate
pytest -q
```

Tes ini hanya menguji fungsi murni: penyusunan konteks, pemetaan hasil pencarian, dan
perakitan prompt. Tidak memanggil API, jadi tidak butuh kunci dan tidak memakan biaya.

---

## Mengubah perilaku

| Ingin | Ubah di |
|---|---|
| Jumlah sumber per pencarian | `MAX_RESULTS` di `brain.py` |
| Panjang potongan tiap sumber | `SNIPPET_LIMIT` di `brain.py` |
| Gaya dan larangan format jawaban | `SYSTEM_PROMPT` di `brain.py` |
| Aturan pembersihan keluaran | `sanitize_answer` di `brain.py` |
| Jumlah riwayat yang dikirim ke model | `MAX_HISTORY` di `brain.py` |
| Batas riwayat di browser | `MAX_STORED_TURNS` di `frontend/app.js` |
| Warna dan tipografi | token di bagian atas `frontend/style.css` |
| Model bahasa | `DEEPSEEK_MODEL` di `.env` |
| Radius pencarian tempat terdekat | `RADIUS_METERS` di `geo.py` (bawaan 2000 meter) |
| Jenis tempat yang dikenali | `CATEGORIES` di `geo.py` |

Karena klien LLM memakai format API yang sama dengan OpenAI, mengganti penyedia cukup dengan
mengubah `DEEPSEEK_BASE_URL` dan `DEEPSEEK_MODEL` di `.env`.

---

## Unggah gambar dan suara

Empat tombol di atas kolom tulis mempercepat pencarian tanpa mengetik. Gambar dan Suara mengisi
kolom tulis dengan teks yang masih bisa kamu sunting sebelum dikirim. Bicara langsung
menjalankan pencarian. Lokasi menyalakan pembacaan posisi untuk pertanyaan tentang tempat
terdekat.

**Gambar.** Pilih berkas, lalu model vision menuliskan satu kalimat deskripsi yang siap dipakai
sebagai kata kunci pencarian. Gambar diperkecil di browser lebih dulu, jadi foto besar pun tetap
muat di bawah batas badan permintaan Vercel. Model bawaannya `deepseek-v4-flash-vision-exp` dari
gateway yang sama dengan model teks, dan bisa diganti lewat `VISION_MODEL`.

**Suara.** Pilih berkas audio, lalu isinya diubah menjadi teks. Gateway yang dipakai sekarang
tidak melayani audio, jadi bagian ini butuh penyedia lain yang formatnya kompatibel dengan
OpenAI. Isi tiga variabel di `.env` atau di dashboard Vercel:

```env
STT_BASE_URL=https://api.groq.com/openai/v1
STT_API_KEY=gsk-kunci-dari-groq
STT_MODEL=whisper-large-v3-turbo
```

Groq punya paket gratis. Selama penyedianya memakai bentuk `/audio/transcriptions` yang sama,
cukup ganti `STT_BASE_URL` dan `STT_MODEL`. Kalau kedua variabel itu kosong, tombol Suara
menampilkan pesan bahwa fiturnya belum dikonfigurasi, bukan gagal diam-diam.

**Bicara.** Tekan tombol ini, lalu ucapkan pertanyaanmu. Bot menyalakan mikrofon, menampilkan
level suara dan durasi, lalu berhenti sendiri setelah kamu diam sekitar 1,6 detik. Hasil
transkripsinya langsung dikirim sebagai pencarian, jadi jawaban mulai mengalir tanpa kamu
menekan tombol kirim. Tekan Bicara sekali lagi untuk berhenti lebih cepat, dan perekaman
otomatis berhenti di batas 60 detik.

Browser akan meminta izin mikrofon sekali. Kalau izin ditolak, muncul pesan yang meminta kamu
mengizinkannya lewat ikon di address bar. Perekaman hanya jalan di `localhost` atau alamat
HTTPS, jadi di produksi tidak ada masalah.

Groq tidak menyediakan transkripsi bertahap kata demi kata, jadi teks muncul setelah kamu
selesai bicara, bukan saat sedang bicara. Yang tampil selama merekam adalah level suara dan
hitungan detik, sebagai tanda mikrofon benar-benar menangkap suara.

**Lokasi.** Tekan tombol ini sekali, izinkan browser membaca posisi, dan tombolnya berubah jadi
hijau dengan tulisan "Lokasi aktif". Setelah itu pertanyaan seperti "ATM terdekat" atau
"warung dekat sini" dijawab dengan tempat yang benar-benar ada di sekitar posisimu, lengkap
dengan perkiraan jaraknya.

Yang terjadi di balik layar: koordinat diubah dulu menjadi nama daerah, lalu tempat dicari
dalam radius 2 km dan diurutkan menurut jarak garis lurus. Hasilnya digabung dengan pencarian
web biasa, dan model menulisnya sebagai paragraf seperti biasa. Kalau pertanyaannya bukan soal
tempat, lokasi sama sekali tidak dipakai, jadi pencarian umum tidak melambat. Kalau layanan
peta sedang tidak bisa dihubungi, jawaban tetap keluar memakai pencarian web saja.

Tidak ada API key tambahan untuk fitur ini. Kedua layanan petanya, Nominatim dan Photon,
memakai data OpenStreetMap dan terbuka tanpa pendaftaran. Yang perlu diketahui soal privasi:
koordinatmu dikirim ke layanan peta itu, bukan ke Tavily dan bukan ke model bahasa. Yang masuk
ke model hanya nama daerah dan daftar tempat beserta jaraknya. Posisi juga hanya hidup di
memori tab, tidak ditulis ke `localStorage`, dan hilang begitu halaman dimuat ulang atau
tombolnya dimatikan.

Browser hanya mau membagi posisi di `localhost` atau alamat HTTPS, jadi di produksi tidak ada
masalah. Kalau izinnya ditolak, muncul pesan yang meminta kamu mengizinkannya lewat ikon di
address bar.

Cakupan datanya bergantung pada OpenStreetMap. ATM, apotek, dan minimarket biasanya lengkap di
kota besar. Warung kecil sering belum dipetakan, jadi kalau hasilnya kosong bukan berarti di
sana tidak ada warung, hanya datanya belum ada. Untuk jawaban yang lebih rapat, layanan peta
berbayar seperti Google Places bisa dipakai dengan mengganti isi `geo.py`; struktur pemanggilannya
sengaja dipisah di modul itu supaya penggantian tidak menyentuh `brain.py`.

Batas berkas 3 MB untuk gambar maupun audio, kira-kira satu sampai dua menit rekaman. Angka itu
dipilih karena Vercel menolak badan permintaan di atas 4,5 MB, dan base64 membengkak sekitar
sepertiga.

## Catatan biaya

Tavily gratis 1.000 pencarian per bulan. DeepSeek berbayar per token, dan untuk satu
pertanyaan dengan lima halaman sumber biayanya di bawah satu sen. Cek halaman harga
masing-masing penyedia untuk angka terbaru.

Kalau ingin menekan biaya, tambahkan cache di memori dengan masa berlaku beberapa menit.
Cukup satu kamus `{query: hasil}` di `brain.py`, tanpa perlu database.

---

## Kalau mau naik versi

Beberapa arah yang wajar setelah ini, dari yang paling murah usaha:

- **Ganti model.** Selama API-nya kompatibel dengan format OpenAI, cukup ubah `.env`.
- **Tambah pencarian paralel.** Untuk pertanyaan majemuk, pecah jadi dua-tiga query dan
  gabungkan hasilnya sebelum masuk prompt.
- **Tambah cache di memori** untuk pertanyaan yang berulang.
- **Ganti antarmuka.** `brain.py` bisa dipanggil dari CLI, bot Telegram, atau WhatsApp tanpa
  diubah sama sekali.
