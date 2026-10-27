"""Tes pencarian tempat sekitar.

Semua fungsi murni dites langsung. Pemanggilan jaringan dipalsukan, jadi tes
ini jalan tanpa internet dan tanpa biaya.
"""

from __future__ import annotations

import asyncio

import pytest

import brain
import geo


# --------------------------------------------------------------------------
# Jarak dan format
# --------------------------------------------------------------------------

def test_haversine_titik_sama_nol():
    assert geo.haversine_meters(-6.2, 106.8, -6.2, 106.8) == pytest.approx(0, abs=0.01)


def test_haversine_satu_derajat_lintang():
    jarak = geo.haversine_meters(0, 0, 1, 0)

    assert jarak == pytest.approx(111_195, rel=0.001)


def test_format_distance_meter_dibulatkan_puluhan():
    assert geo.format_distance(203) == "200 m"
    assert geo.format_distance(683) == "680 m"


def test_format_distance_kilometer_pakai_koma():
    assert geo.format_distance(1234) == "1,2 km"
    assert geo.format_distance(2000) == "2,0 km"


# --------------------------------------------------------------------------
# Mengenali pertanyaan setempat
# --------------------------------------------------------------------------

def test_match_categories_mengenali_atm():
    hasil = geo.match_categories("atm terdekat di mana ya")

    assert [c.key for c in hasil] == ["atm"]


def test_match_categories_mengenali_warung_dan_apotek():
    hasil = geo.match_categories("cari warung dan apotek dekat sini")
    kunci = [c.key for c in hasil]

    assert "warung" in kunci
    assert "apotek" in kunci


def test_match_categories_mengabaikan_kata_yang_mengandung():
    assert geo.match_categories("atmosfer dan bankan aneh") == []


def test_match_categories_dibatasi_tiga():
    hasil = geo.match_categories("atm bank warung apotek spbu laundry")

    assert len(hasil) == 3


def test_is_local_question_benar_untuk_kata_lokasi():
    assert geo.is_local_question("di mana pom bensin terdekat") is True


def test_is_local_question_benar_untuk_jenis_tempat():
    assert geo.is_local_question("rekomendasi warung") is True


def test_is_local_question_salah_untuk_topik_biasa():
    assert geo.is_local_question("berapa harga bitcoin sekarang") is False


# --------------------------------------------------------------------------
# Kata kunci yang dikirim ke Photon
# --------------------------------------------------------------------------

def test_build_photon_queries_tanpa_duplikat():
    hasil = geo.build_photon_queries([geo.CATEGORIES[0], geo.CATEGORIES[0]])
    kunci = [(q, t) for q, t, _ in hasil]

    assert len(kunci) == len(set(kunci))


def test_build_photon_queries_dibatasi_enam():
    semua = list(geo.CATEGORIES)
    hasil = geo.build_photon_queries(semua)

    assert len(hasil) == geo.MAX_PHOTON_CALLS


def test_build_photon_queries_membawa_kategori():
    hasil = geo.build_photon_queries([geo.CATEGORIES[0]])

    assert hasil[0][2] == "atm"


# --------------------------------------------------------------------------
# Membaca balasan Photon
# --------------------------------------------------------------------------

def _feature(name, lat, lon, key="amenity", value="atm"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "osm_key": key, "osm_value": value},
    }


def test_parse_photon_menghitung_jarak_dan_mengurutkan():
    payload = {
        "features": [
            _feature("Jauh", -6.2400, 106.8533),
            _feature("Dekat", -6.2270, 106.8533),
        ]
    }

    hasil = geo.parse_photon(payload, -6.2266, 106.8533, "atm")

    assert [p.name for p in hasil] == ["Dekat", "Jauh"]
    assert hasil[0].distance < hasil[1].distance


def test_parse_photon_membuang_yang_di_luar_radius():
    payload = {"features": [_feature("Bandung", -6.9175, 107.6191)]}

    assert geo.parse_photon(payload, -6.2266, 106.8533, "atm") == []


def test_parse_photon_membuang_tanpa_nama():
    payload = {"features": [_feature("", -6.2266, 106.8533)]}

    assert geo.parse_photon(payload, -6.2266, 106.8533, "atm") == []


def test_parse_photon_menerjemahkan_jenis():
    payload = {"features": [_feature("Apotek Sehat", -6.2266, 106.8533, "amenity", "pharmacy")]}

    assert geo.parse_photon(payload, -6.2266, 106.8533, "apotek")[0].kind == "apotek"


def test_parse_photon_tahan_terhadap_balasan_rusak():
    assert geo.parse_photon({}, -6.2, 106.8) == []
    assert geo.parse_photon({"features": [{"geometry": {"coordinates": []}}]}, -6.2, 106.8) == []


def test_merge_places_membuang_duplikat_dan_mengurutkan():
    a = [geo.Place("Alfamart", "minimarket", -6.2270, 106.8533, 780.0, "warung")]
    b = [geo.Place("Alfamart", "minimarket", -6.2270, 106.8533, 780.0, "warung")]
    c = [geo.Place("ATM", "ATM", -6.2267, 106.8533, 200.0, "atm")]

    hasil = geo.merge_places([a, b, c])

    assert [p.name for p in hasil] == ["ATM", "Alfamart"]


def test_merge_places_membatasi_per_kategori():
    banyak = [
        geo.Place(f"Toko {i}", "minimarket", -6.2270, 106.8533, 100.0 + i, "warung")
        for i in range(20)
    ]

    hasil = geo.merge_places([banyak])

    assert len(hasil) == geo.MAX_PER_CATEGORY


# --------------------------------------------------------------------------
# Nama daerah dan bahan prompt
# --------------------------------------------------------------------------

def test_format_area_menyusun_tiga_bagian_pendek():
    address = {
        "village": "Tebet Timur",
        "suburb": "Tebet",
        "city_district": "Jakarta Selatan",
        "city": "Daerah Khusus Ibukota Jakarta",
        "country": "Indonesia",
    }

    assert geo.format_area(address) == "Tebet Timur, Tebet, Jakarta Selatan"


def test_format_area_tahan_kosong():
    assert geo.format_area({}) == ""


def test_format_places_block_memuat_nama_dan_jarak():
    places = [geo.Place("ATM Bank Mandiri", "ATM", -6.2270, 106.8533, 203.0, "atm")]
    blok = geo.format_places_block("Tebet Timur, Tebet, Jakarta Selatan", places, 30)

    assert "ATM Bank Mandiri" in blok
    assert "200 m" in blok
    assert "Tebet Timur" in blok
    assert "akurasi posisi sekitar 30 meter" in blok
    assert "http" not in blok


def test_format_places_block_kosong_tanpa_data():
    assert geo.format_places_block("", []) == ""


def test_format_places_block_mengabarkan_radius_kosong():
    blok = geo.format_places_block("Tebet", [])

    assert "radius 2 km" in blok


# --------------------------------------------------------------------------
# Validasi koordinat
# --------------------------------------------------------------------------

def test_valid_coords_menerima_nilai_wajar():
    assert geo.valid_coords({"lat": -6.2, "lon": 106.8}) == (-6.2, 106.8)


def test_valid_coords_menolak_di_luar_rentang():
    assert geo.valid_coords({"lat": -91, "lon": 106.8}) == (None, None)
    assert geo.valid_coords({"lat": -6.2, "lon": 181}) == (None, None)


def test_valid_coords_menolak_teks_dan_none():
    assert geo.valid_coords(None) == (None, None)
    assert geo.valid_coords({"lat": "bukan", "lon": 1}) == (None, None)


# --------------------------------------------------------------------------
# Jaringan dipalsukan
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Meniru httpx.AsyncClient untuk Nominatim dan Photon."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None):
        if "nominatim" in url:
            return _FakeResponse(
                200,
                {
                    "address": {
                        "village": "Tebet Timur",
                        "suburb": "Tebet",
                        "city_district": "Jakarta Selatan",
                    }
                },
            )
        return _FakeResponse(
            200,
            {
                "features": [
                    _feature("ATM Bank Mandiri", -6.2270, 106.8533, "amenity", "atm"),
                    _feature("ATM Jauh", -6.3000, 106.8533, "amenity", "atm"),
                ]
            },
        )


def test_reverse_area_membaca_nominatim(monkeypatch):
    geo._AREA_CACHE.clear()
    monkeypatch.setattr(geo.httpx, "AsyncClient", _FakeClient)

    area = asyncio.run(geo.reverse_area(-6.2266, 106.8533))

    assert area == "Tebet Timur, Tebet, Jakarta Selatan"


def test_reverse_area_memakai_cache(monkeypatch):
    geo._AREA_CACHE.clear()
    panggilan = {"n": 0}

    class _Hitung(_FakeClient):
        async def get(self, url, params=None, headers=None):
            panggilan["n"] += 1
            return await super().get(url, params=params, headers=headers)

    monkeypatch.setattr(geo.httpx, "AsyncClient", _Hitung)

    asyncio.run(geo.reverse_area(-6.2266, 106.8533))
    asyncio.run(geo.reverse_area(-6.2266, 106.8533))

    assert panggilan["n"] == 1


def test_reverse_area_gagal_diam_diam(monkeypatch):
    geo._AREA_CACHE.clear()

    class _Rusak(_FakeClient):
        async def get(self, url, params=None, headers=None):
            raise RuntimeError("jaringan mati")

    monkeypatch.setattr(geo.httpx, "AsyncClient", _Rusak)

    assert asyncio.run(geo.reverse_area(-6.2266, 106.8533)) == ""


def test_nearby_places_menggabungkan_hasil(monkeypatch):
    monkeypatch.setattr(geo.httpx, "AsyncClient", _FakeClient)

    hasil = asyncio.run(
        geo.nearby_places(-6.2266, 106.8533, [geo.CATEGORIES[0]])
    )

    assert [p.name for p in hasil] == ["ATM Bank Mandiri"]


def test_local_context_menggabungkan_daerah_dan_tempat(monkeypatch):
    geo._AREA_CACHE.clear()
    monkeypatch.setattr(geo.httpx, "AsyncClient", _FakeClient)

    area, places = asyncio.run(geo.local_context(-6.2266, 106.8533, "atm terdekat"))

    assert area.startswith("Tebet Timur")
    assert places and places[0].name == "ATM Bank Mandiri"


# --------------------------------------------------------------------------
# Sambungan ke prompt
# --------------------------------------------------------------------------

def test_build_messages_menyisipkan_bahan_lokasi():
    pesan = brain.build_messages(
        "atm terdekat",
        [],
        [brain.Source(1, "T", "https://a.test", "isi")],
        today="2026-10-27",
        places="Daerah: Tebet.\nATM Bank Mandiri (ATM) - 200 m",
    )

    assert "ATM Bank Mandiri" in pesan[0]["content"]
    assert "Tebet" in pesan[0]["content"]


def test_build_messages_tanpa_lokasi_tetap_jalan():
    pesan = brain.build_messages("halo", [], [], today="2026-10-27")

    assert "Daerah:" not in pesan[0]["content"]
