"""Tempat di sekitar pengguna, memakai OpenStreetMap tanpa kunci API.

Dua layanan dipakai. Nominatim mengubah koordinat menjadi nama daerah, dan
Photon mencari tempat di sekitar koordinat lalu jaraknya dihitung sendiri di
sini. Keduanya gratis. Kalau salah satu gagal atau lambat, bot tetap menjawab
memakai hasil pencarian web biasa.

Tidak ada data pengguna yang disimpan. Cache nama daerah hanya hidup di memori
proses dan kuncinya dibulatkan sekitar satu kilometer, jadi tidak bisa dipakai
untuk melacak siapa pun.

Catatan sopan santun layanan: Nominatim membatasi satu permintaan per detik,
karena itu hasilnya di-cache. Photon dibatasi enam permintaan per pertanyaan.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

import httpx

RADIUS_METERS = 2000
MAX_PER_CATEGORY = 6
MAX_TOTAL = 12
MAX_PHOTON_CALLS = 6
PHOTON_LIMIT = 50
LOCATION_BIAS = 0.1
TIMEOUT_SECONDS = 8.0

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "AmSure/1.0 (personal search bot)"

# Nama daerah yang terlalu panjang atau terlalu umum untuk ditulis di jawaban.
SKIP_AREA = {
    "indonesia",
    "daerah khusus ibukota jakarta",
    "dki jakarta",
    "jakarta raya",
}


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    lat: float
    lon: float
    distance: float
    category: str


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    keywords: tuple[str, ...]
    queries: tuple[tuple[str, Optional[str]], ...]


CATEGORIES: tuple[Category, ...] = (
    Category(
        "atm",
        "ATM",
        ("atm", "anjungan tunai mandiri"),
        (("atm", "amenity:atm"),),
    ),
    Category(
        "bank",
        "bank",
        ("bank", "kantor bank"),
        (("bank", "amenity:bank"),),
    ),
    Category(
        "warung",
        "warung dan minimarket",
        ("warung", "minimarket", "indomaret", "alfamart", "toko kelontong", "kelontong"),
        (
            ("warung", None),
            ("alfamart", "shop:convenience"),
            ("indomaret", "shop:convenience"),
            ("minimarket", "shop:convenience"),
        ),
    ),
    Category(
        "apotek",
        "apotek",
        ("apotek", "apotik", "farmasi"),
        (("apotek", "amenity:pharmacy"),),
    ),
    Category(
        "spbu",
        "SPBU",
        ("spbu", "pom bensin", "pom bensin terdekat", "pengisian bahan bakar"),
        (("spbu", "amenity:fuel"), ("pom bensin", None)),
    ),
    Category(
        "makan",
        "tempat makan",
        ("restoran", "rumah makan", "warung makan", "tempat makan", "kafe", "cafe", "kopi"),
        (
            ("restoran", "amenity:restaurant"),
            ("makanan", "amenity:fast_food"),
            ("kafe", "amenity:cafe"),
        ),
    ),
    Category(
        "rumahsakit",
        "rumah sakit",
        ("rumah sakit", "hospital"),
        (("rumah sakit", "amenity:hospital"),),
    ),
    Category(
        "klinik",
        "klinik",
        ("klinik", "puskesmas", "dokter praktik"),
        (("klinik", "amenity:clinic"), ("puskesmas", None)),
    ),
    Category(
        "bengkel",
        "bengkel",
        ("bengkel", "tambal ban", "service motor", "servis motor"),
        (("bengkel", "shop:car_repair"), ("bengkel motor", "shop:motorcycle_repair")),
    ),
    Category(
        "laundry",
        "laundry",
        ("laundry", "binatu", "cuci pakaian"),
        (("laundry", "shop:laundry"),),
    ),
    Category(
        "ibadah",
        "tempat ibadah",
        ("masjid", "musholla", "mushola", "surau", "gereja", "pura", "vihara"),
        (("masjid", "amenity:place_of_worship"),),
    ),
    Category(
        "hotel",
        "penginapan",
        ("hotel", "penginapan", "losmen", "homestay", "hostel"),
        (("hotel", "tourism:hotel"),),
    ),
    Category(
        "parkir",
        "parkir",
        ("parkir", "tempat parkir"),
        (("parkir", "amenity:parking"),),
    ),
    Category(
        "sekolah",
        "sekolah",
        ("sekolah", "kampus", "universitas"),
        (("sekolah", "amenity:school"),),
    ),
)

LOCAL_HINTS = (
    "terdekat",
    "paling dekat",
    "dekat sini",
    "dekat rumah",
    "di dekat",
    "di sekitar",
    "sekitar sini",
    "sekitaran",
    "dari sini",
    "posisi saya",
    "lokasi saya",
    "nearby",
)

KIND_LABELS = {
    ("amenity", "atm"): "ATM",
    ("amenity", "bank"): "bank",
    ("shop", "convenience"): "minimarket",
    ("shop", "supermarket"): "supermarket",
    ("shop", "greengrocer"): "toko sayur",
    ("shop", "butcher"): "toko daging",
    ("shop", "bakery"): "toko roti",
    ("amenity", "pharmacy"): "apotek",
    ("amenity", "fuel"): "SPBU",
    ("amenity", "restaurant"): "rumah makan",
    ("amenity", "fast_food"): "makanan cepat saji",
    ("amenity", "cafe"): "kafe",
    ("amenity", "hospital"): "rumah sakit",
    ("amenity", "clinic"): "klinik",
    ("amenity", "doctors"): "praktik dokter",
    ("shop", "car_repair"): "bengkel",
    ("shop", "motorcycle_repair"): "bengkel motor",
    ("shop", "laundry"): "laundry",
    ("amenity", "place_of_worship"): "tempat ibadah",
    ("tourism", "hotel"): "penginapan",
    ("tourism", "guest_house"): "penginapan",
    ("amenity", "parking"): "parkir",
    ("amenity", "school"): "sekolah",
    ("amenity", "university"): "kampus",
    ("amenity", "police"): "kantor polisi",
    ("amenity", "post_office"): "kantor pos",
}


# --------------------------------------------------------------------------
# Fungsi murni (tanpa jaringan) - ini yang dites
# --------------------------------------------------------------------------

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Jarak garis lurus antara dua koordinat, dalam meter."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def format_distance(meters: float) -> str:
    """Jarak yang enak dibaca: '380 m' atau '1,2 km'."""
    if meters < 1000:
        return f"{int(round(meters / 10.0) * 10)} m"
    return f"{meters / 1000.0:.1f}".replace(".", ",") + " km"


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern:
    return re.compile(
        r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])",
        re.IGNORECASE,
    )


def _keyword_positions(text: str, keyword: str) -> int:
    match = _keyword_pattern(keyword).search(text)
    return match.start() if match else -1


def match_categories(text: str, limit: int = 3) -> list[Category]:
    """Tebak kategori tempat yang dimaksud, urut menurut kemunculan di kalimat."""
    teks = text or ""
    ditemukan: list[tuple[int, Category]] = []
    for category in CATEGORIES:
        posisi = [
            _keyword_positions(teks, word)
            for word in category.keywords
        ]
        posisi = [p for p in posisi if p >= 0]
        if posisi:
            ditemukan.append((min(posisi), category))

    ditemukan.sort(key=lambda item: item[0])
    return [category for _, category in ditemukan[:limit]]


def is_local_question(text: str) -> bool:
    """Pertanyaan dianggap setempat kalau menyebut kata lokasi atau jenis tempat."""
    teks = (text or "").lower()
    if any(hint in teks for hint in LOCAL_HINTS):
        return True
    return bool(match_categories(teks))


def build_photon_queries(
    categories: Iterable[Category],
) -> list[tuple[str, Optional[str], str]]:
    """Susun daftar (kata kunci, filter OSM, kategori), tanpa duplikat."""
    hasil: list[tuple[str, Optional[str], str]] = []
    terpakai: set[tuple[str, str]] = set()

    for category in categories:
        for query, tag in category.queries:
            kunci = (query.lower(), (tag or "").lower())
            if kunci in terpakai:
                continue
            terpakai.add(kunci)
            hasil.append((query, tag, category.key))
            if len(hasil) >= MAX_PHOTON_CALLS:
                return hasil

    return hasil


def kind_label(osm_key: Optional[str], osm_value: Optional[str]) -> str:
    """Terjemahkan tag OSM jadi sebutan yang wajar dalam Bahasa Indonesia."""
    key = (osm_key or "").strip().lower()
    value = (osm_value or "").strip().lower()
    label = KIND_LABELS.get((key, value))
    if label:
        return label
    if value:
        return value.replace("_", " ")
    return "tempat"


def parse_photon(
    payload: dict,
    lat: float,
    lon: float,
    category: str = "",
    radius: float = RADIUS_METERS,
) -> list[Place]:
    """Ubah balasan Photon jadi Place yang sudah punya jarak dan tersaring radius."""
    places: list[Place] = []

    for feature in (payload or {}).get("features") or []:
        properties = feature.get("properties") or {}
        coordinates = ((feature.get("geometry") or {}).get("coordinates") or [])[:2]
        if len(coordinates) < 2:
            continue

        try:
            place_lon = float(coordinates[0])
            place_lat = float(coordinates[1])
        except (TypeError, ValueError):
            continue

        name = (properties.get("name") or "").strip()
        if not name:
            continue

        distance = haversine_meters(lat, lon, place_lat, place_lon)
        if distance > radius:
            continue

        places.append(
            Place(
                name=name,
                kind=kind_label(properties.get("osm_key"), properties.get("osm_value")),
                lat=place_lat,
                lon=place_lon,
                distance=distance,
                category=category,
            )
        )

    places.sort(key=lambda place: place.distance)
    return places


def merge_places(groups: Iterable[list[Place]]) -> list[Place]:
    """Gabungkan hasil beberapa kategori, buang duplikat, urutkan menurut jarak."""
    terlihat: set[tuple[str, float, float]] = set()
    per_kategori: dict[str, int] = {}
    dipilih: list[Place] = []

    for group in groups:
        for place in sorted(group, key=lambda item: item.distance):
            kunci = (place.name.lower(), round(place.lat, 4), round(place.lon, 4))
            if kunci in terlihat:
                continue
            if per_kategori.get(place.category, 0) >= MAX_PER_CATEGORY:
                continue

            terlihat.add(kunci)
            per_kategori[place.category] = per_kategori.get(place.category, 0) + 1
            dipilih.append(place)

    dipilih.sort(key=lambda place: place.distance)
    return dipilih[:MAX_TOTAL]


def format_area(address: dict) -> str:
    """Susun nama daerah yang pendek dari balasan Nominatim."""
    bagian: list[str] = []
    for key in ("village", "suburb", "city_district", "town", "municipality", "city", "state"):
        value = (address.get(key) or "").strip()
        if not value:
            continue
        if value.lower() in SKIP_AREA:
            continue
        if value.lower() in {bagian_lama.lower() for bagian_lama in bagian}:
            continue
        bagian.append(value)
    return ", ".join(bagian[:3])


def format_places_block(
    area: str,
    places: list[Place],
    accuracy: Optional[float] = None,
    radius: float = RADIUS_METERS,
) -> str:
    """Susun bahan lokasi untuk dimasukkan ke prompt. Kosong kalau tidak ada apa-apa."""
    if not places and not area:
        return ""

    baris = ["Tempat di sekitar pengguna saat ini."]

    if area:
        keterangan = ""
        if accuracy and accuracy > 0:
            keterangan = f" (akurasi posisi sekitar {int(round(accuracy / 10.0) * 10)} meter)"
        baris.append(f"Daerah: {area}{keterangan}.")

    if places:
        baris.append(
            "Daftar berikut diurutkan menurut jarak garis lurus dari posisi pengguna:"
        )
        for place in places:
            baris.append(f"{place.name} ({place.kind}) - {format_distance(place.distance)}")
    else:
        radius_km = radius / 1000.0
        baris.append(
            f"Tidak ada tempat yang cocok ditemukan dalam radius {radius_km:.0f} km."
        )

    return "\n".join(baris)


def valid_coords(location: Optional[dict]) -> tuple[Optional[float], Optional[float]]:
    """Ambil lat/lon yang masuk akal dari payload klien. Selain itu, None."""
    if not isinstance(location, dict):
        return None, None
    try:
        lat = float(location.get("lat"))
        lon = float(location.get("lon"))
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None, None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None
    return lat, lon


# --------------------------------------------------------------------------
# Jaringan
# --------------------------------------------------------------------------

_AREA_CACHE: dict[tuple[float, float], str] = {}
_AREA_CACHE_MAX = 256


def _headers() -> dict:
    return {"User-Agent": os.environ.get("GEO_USER_AGENT", USER_AGENT)}


async def reverse_area(lat: float, lon: float) -> str:
    """Nama daerah dari koordinat. Gagal atau kosong bukan masalah, kembalikan ''."""
    kunci = (round(lat, 2), round(lon, 2))
    if kunci in _AREA_CACHE:
        return _AREA_CACHE[kunci]

    params = {
        "format": "jsonv2",
        "lat": lat,
        "lon": lon,
        "zoom": 16,
        "addressdetails": 1,
        "accept-language": "id",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=_headers())
        if resp.status_code >= 400:
            return ""
        area = format_area((resp.json() or {}).get("address") or {})
    except Exception:
        return ""

    if area:
        if len(_AREA_CACHE) >= _AREA_CACHE_MAX:
            _AREA_CACHE.clear()
        _AREA_CACHE[kunci] = area

    return area


async def _photon(
    client: httpx.AsyncClient,
    query: str,
    tag: Optional[str],
    lat: float,
    lon: float,
    category: str,
) -> list[Place]:
    params = {
        "q": query,
        "lat": lat,
        "lon": lon,
        "limit": PHOTON_LIMIT,
        "location_bias_scale": LOCATION_BIAS,
    }
    if tag:
        params["osm_tag"] = tag

    try:
        resp = await client.get(PHOTON_URL, params=params, headers=_headers())
    except Exception:
        return []

    if resp.status_code >= 400:
        return []

    try:
        payload = resp.json()
    except Exception:
        return []

    return parse_photon(payload, lat, lon, category)


async def nearby_places(lat: float, lon: float, categories: Iterable[Category]) -> list[Place]:
    """Cari tempat sekitar secara paralel, lalu gabungkan dan urutkan."""
    queries = build_photon_queries(categories)
    if not queries:
        return []

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        groups = await asyncio.gather(
            *[
                _photon(client, query, tag, lat, lon, category)
                for query, tag, category in queries
            ]
        )

    return merge_places(groups)


async def local_context(
    lat: float,
    lon: float,
    message: str,
) -> tuple[str, list[Place]]:
    """Nama daerah dan daftar tempat terdekat. Tidak pernah melempar error."""
    categories = match_categories(message)
    area, places = await asyncio.gather(
        reverse_area(lat, lon),
        nearby_places(lat, lon, categories),
    )
    return area, places
