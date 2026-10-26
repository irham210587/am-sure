"""Tes deteksi kunci contoh, supaya health check tidak berbohong.

Kalau kunci masih placeholder, /api/health harus bilang belum siap. Tanpa
ini, aplikasi terlihat sehat padahal setiap pertanyaan akan gagal 401.
"""

from __future__ import annotations

import main


def test_kunci_kosong_dianggap_belum_diisi():
    assert main.is_real_key("") is False
    assert main.is_real_key("   ") is False
    assert main.is_real_key(None) is False


def test_nilai_contoh_ditolak():
    assert main.is_real_key("sk-tkx-ISI-KUNCI-TOKENOMIX-KAMU") is False
    assert main.is_real_key("sk-isi-di-sini") is False
    assert main.is_real_key("tvly-isi-di-sini") is False


def test_kunci_terisi_diterima():
    assert main.is_real_key("sk-tkx-abc123def456") is True
    assert main.is_real_key("tvly-dev-32SW6B-moT4") is True
