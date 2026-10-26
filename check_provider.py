"""Uji cepat koneksi ke penyedia LLM yang terpasang di .env.

Membaca .env yang sama dengan aplikasi, jadi kalau skrip ini berhasil,
bot juga akan berhasil.

Jalankan:
    .venv/bin/python check_provider.py
    .venv/bin/python check_provider.py --models
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PLACEHOLDER_HINTS = ("ISI-KUNCI", "isi-di-sini", "...")


def read_config() -> tuple[str, str, str]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    return api_key, base_url, model


def looks_unset(api_key: str) -> bool:
    if not api_key:
        return True
    return any(hint in api_key for hint in PLACEHOLDER_HINTS)


def show_config(api_key: str, base_url: str, model: str) -> None:
    masked = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 12 else "(terlalu pendek)"
    print(f"base_url : {base_url}")
    print(f"model    : {model}")
    print(f"api_key  : {masked}")
    print()


def chat_once(client: OpenAI, model: str) -> int:
    try:
        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Halo! Jawab satu kalimat saja."}],
            max_tokens=60,
        )
    except Exception as exc:
        print("GAGAL memanggil model.")
        print(f"  {type(exc).__name__}: {exc}")
        print()
        print("Kalau pesannya soal model, jalankan dengan --models untuk melihat")
        print("nama model yang tersedia di penyedia ini.")
        return 1

    print("BERHASIL. Balasan model:")
    print(f"  {res.choices[0].message.content.strip()}")
    return 0


def list_models(client: OpenAI) -> int:
    try:
        models = client.models.list()
    except Exception as exc:
        print("GAGAL mengambil daftar model.")
        print(f"  {type(exc).__name__}: {exc}")
        return 1

    ids = sorted(m.id for m in models.data if getattr(m, "id", None))
    if not ids:
        print("Daftar model kosong.")
        return 1

    print(f"{len(ids)} model tersedia:")
    for model_id in ids:
        mark = "  <- dipakai sekarang" if model_id == read_config()[2] else ""
        print(f"  {model_id}{mark}")
    return 0


def main() -> int:
    api_key, base_url, model = read_config()
    show_config(api_key, base_url, model)

    if looks_unset(api_key):
        print("Kunci belum diisi. Buka .env lalu ganti DEEPSEEK_API_KEY")
        print("dengan kunci asli dari dashboard penyedia.")
        return 1

    client = OpenAI(base_url=base_url, api_key=api_key)

    if "--models" in sys.argv:
        return list_models(client)

    return chat_once(client, model)


if __name__ == "__main__":
    sys.exit(main())
