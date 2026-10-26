"""Tes validasi unggahan gambar dan audio.

Semua yang dites di sini fungsi murni, jadi tidak ada panggilan jaringan dan
tidak ada biaya.
"""

from __future__ import annotations

import pytest

import brain


def test_check_upload_menolak_jenis_tak_didukung():
    pesan = brain.check_upload("application/pdf", 1024, brain.ALLOWED_IMAGE)

    assert "tidak didukung" in pesan


def test_check_upload_menolak_berkas_kosong():
    assert brain.check_upload("image/png", 0, brain.ALLOWED_IMAGE) == "Berkas kosong."


def test_check_upload_menolak_berkas_terlalu_besar():
    pesan = brain.check_upload("image/png", brain.MAX_UPLOAD_BYTES + 1, brain.ALLOWED_IMAGE)

    assert "melebihi batas" in pesan


def test_check_upload_menerima_berkas_wajar():
    assert brain.check_upload("image/png", 1024, brain.ALLOWED_IMAGE) == ""


def test_check_upload_mengabaikan_parameter_setelah_titik_koma():
    assert brain.check_upload("image/jpeg; charset=binary", 1024, brain.ALLOWED_IMAGE) == ""


def test_check_upload_audio_menerima_webm():
    assert brain.check_upload("audio/webm", 2048, brain.ALLOWED_AUDIO) == ""


def test_check_upload_menerima_webm_dengan_codec_dari_browser():
    assert brain.check_upload("audio/webm;codecs=opus", 2048, brain.ALLOWED_AUDIO) == ""


def test_check_upload_menerima_mp4_yang_dipakai_safari():
    assert brain.check_upload("audio/mp4", 2048, brain.ALLOWED_AUDIO) == ""


def test_decode_upload_menerima_base64_biasa():
    assert brain.decode_upload("aGVsbG8=") == b"hello"


def test_decode_upload_menerima_data_url():
    assert brain.decode_upload("data:image/png;base64,aGVsbG8=") == b"hello"


def test_decode_upload_menolak_isi_tidak_sah():
    with pytest.raises(ValueError):
        brain.decode_upload("bukan base64!!")


def test_stt_belum_siap_tanpa_kunci(monkeypatch):
    monkeypatch.delenv("STT_BASE_URL", raising=False)
    monkeypatch.delenv("STT_API_KEY", raising=False)

    assert brain.stt_ready() is False


def test_stt_siap_saat_kedua_nilai_terisi(monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://contoh.test/v1")
    monkeypatch.setenv("STT_API_KEY", "abc")

    assert brain.stt_ready() is True


def test_nama_model_vision_bisa_diganti(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "model-lain")

    assert brain.vision_model_name() == "model-lain"


def test_nama_model_vision_ada_bawaan(monkeypatch):
    monkeypatch.delenv("VISION_MODEL", raising=False)

    assert brain.vision_model_name() == brain.VISION_MODEL_DEFAULT
