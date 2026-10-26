"""Tes penjaga kunci akses untuk deployment publik.

Penjaga ini hanya aktif kalau APP_ACCESS_KEY di-set. Saat mengembangkan di
komputer sendiri, semua permintaan tetap lolos.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import main


def test_penjaga_tidak_aktif_tanpa_kunci(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "")

    asyncio.run(main.require_access(None))


def test_penjaga_menolak_header_kosong(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "rahasia-panjang")

    with pytest.raises(HTTPException) as info:
        asyncio.run(main.require_access(None))

    assert info.value.status_code == 401


def test_penjaga_menolak_header_salah(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "rahasia-panjang")

    with pytest.raises(HTTPException) as info:
        asyncio.run(main.require_access("tebakan-ngawur"))

    assert info.value.status_code == 401


def test_penjaga_menerima_header_benar(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "rahasia-panjang")

    asyncio.run(main.require_access("rahasia-panjang"))


def test_health_melaporkan_perlunya_kunci(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "rahasia-panjang")

    assert asyncio.run(main.health())["access_required"] is True


def test_health_tanpa_kunci_akses(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_KEY", "")

    assert asyncio.run(main.health())["access_required"] is False
