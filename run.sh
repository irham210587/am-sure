#!/usr/bin/env bash
# Telusur — nyalakan bot dalam satu perintah.
#
#   ./run.sh              jalankan di port 8000
#   PORT=8001 ./run.sh    jalankan di port lain
#
# Skrip ini aman dijalankan berulang: venv dan dependency hanya dibuat sekali.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"

stop() {
  printf '\n  %s\n\n' "$1"
  exit 1
}

# ---- Python ----

command -v python3 >/dev/null 2>&1 \
  || stop "Python 3 tidak ditemukan. Install dulu: brew install python"

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || stop "Butuh Python 3.10 atau lebih baru. Versi sekarang: $(python3 -V 2>&1)"

# ---- virtual environment ----

if [ ! -d .venv ]; then
  printf '→ Membuat virtual environment di .venv\n'
  python3 -m venv .venv
fi

# ---- dependency ----

printf '→ Memeriksa dependency\n'
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# ---- konfigurasi ----

if [ ! -f .env ]; then
  cp .env.example .env
  printf '\n  File .env sudah dibuat dari .env.example.\n'
  printf '  Buka .env, isi DEEPSEEK_API_KEY dan TAVILY_API_KEY, lalu jalankan lagi:\n\n'
  printf '      ./run.sh\n\n'
  exit 1
fi

grep -qE '^DEEPSEEK_API_KEY=.+' .env \
  || stop "DEEPSEEK_API_KEY belum diisi di .env"

grep -qE '^TAVILY_API_KEY=.+' .env \
  || stop "TAVILY_API_KEY belum diisi di .env"

if grep -qE '^[^#].*(isi-di-sini|ISI-KUNCI)' .env; then
  stop "Masih ada nilai contoh di .env. Ganti DEEPSEEK_API_KEY dan TAVILY_API_KEY dengan kunci yang asli."
fi

# ---- jalan ----

printf '→ Telusur berjalan di http://127.0.0.1:%s\n' "$PORT"
printf '  Tekan Ctrl+C untuk berhenti.\n\n'

exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload
