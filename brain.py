"""Inti mesin: tulis ulang query -> cari web -> susun prompt -> stream jawaban.

Tidak ada database. Setiap request membawa riwayatnya sendiri dari browser,
jadi proses ini sepenuhnya tanpa status.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

import httpx
from openai import AsyncOpenAI
from tavily import AsyncTavilyClient

import geo

MAX_HISTORY = 6
MAX_RESULTS = 5
SNIPPET_LIMIT = 1400
RETRY_DELAY_SECONDS = 1.5


@dataclass
class Source:
    index: int
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Klien
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def llm() -> AsyncOpenAI:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY belum di-set di file .env")
    return AsyncOpenAI(
        api_key=key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


@lru_cache(maxsize=1)
def searcher() -> AsyncTavilyClient:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TAVILY_API_KEY belum di-set di file .env")
    return AsyncTavilyClient(api_key=key)


def model_name() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


VISION_MODEL_DEFAULT = "deepseek-v4-flash-vision-exp"


def vision_model_name() -> str:
    return os.environ.get("VISION_MODEL", VISION_MODEL_DEFAULT)


# --------------------------------------------------------------------------
# Fungsi murni (tanpa jaringan) - ini yang dites
# --------------------------------------------------------------------------

def map_results(raw: dict) -> list[Source]:
    """Ubah balasan mentah Tavily jadi daftar Source yang sudah rapi."""
    sources: list[Source] = []
    for i, item in enumerate(raw.get("results") or [], start=1):
        title = (item.get("title") or "").strip() or "Tanpa judul"
        url = (item.get("url") or "").strip()
        snippet = (item.get("content") or "").strip()
        if len(snippet) > SNIPPET_LIMIT:
            snippet = snippet[:SNIPPET_LIMIT].rstrip() + "..."
        sources.append(Source(index=i, title=title, url=url, snippet=snippet))
    return sources


def build_context(sources: list[Source]) -> str:
    """Susun sumber jadi blok bernomor yang bisa disitasi model."""
    if not sources:
        return "(Tidak ada hasil pencarian.)"
    blocks = []
    for s in sources:
        blocks.append(f"[{s.index}] {s.title}\nURL: {s.url}\n{s.snippet}")
    return "\n\n".join(blocks)


SYSTEM_PROMPT = """Kamu asisten yang menjawab dengan tenang, runtut, dan langsung.

Tanggal hari ini: {today}.

Di bawah ada bahan dari web dan, kalau tersedia, daftar tempat di sekitar pengguna. Keduanya satu-satunya dasar jawabanmu. Pengguna tidak melihat bahan itu dan tidak tahu ada pencarian, jadi jangan pernah merujuknya.

Cara menyusun jawaban:
1. Kalimat pertama langsung menjawab inti pertanyaan. Sisanya penjelasan yang mengalir.
2. Tulis sebagai paragraf naratif. Dilarang menyusun daftar bernomor, dilarang memakai bullet, dilarang memakai tanda hubung atau bintang di awal baris.
3. Dilarang menulis alamat situs, tautan, atau nama domain dalam bentuk apa pun.
4. Dilarang menulis frasa seperti "menurut sumber", "berdasarkan pencarian", "dari hasil pencarian", "sumber:", atau menyebut nomor sumber.
5. Dilarang mengarang angka, tanggal, nama, atau peristiwa. Kalau bahan tidak memuat jawabannya, jawab dengan satu atau dua kalimat sopan bahwa informasi itu belum tersedia, tanpa mengutip bahan mentah.
6. Kalau bahan saling bertentangan, sebutkan bahwa ada keterangan yang berbeda, tanpa menyebut asalnya.
7. Kalau pertanyaannya menanyakan tempat terdekat, dahulukan tempat dari daftar di bawah dan sebutkan perkiraan jaraknya di dalam kalimat. Jangan menyebut koordinat, dan jangan menyebut tempat yang tidak ada di daftar maupun di bahan.
8. Bahasa Indonesia. Dua sampai empat paragraf pendek, kecuali pertanyaannya memang menuntut lebih.

Bahan:
{context}

{places}"""


NOT_FOUND_TEXT = (
    "Maaf, informasi itu belum tersedia saat ini. Coba tanyakan dengan kata lain, "
    "atau sebutkan topiknya lebih spesifik."
)


def build_messages(
    message: str,
    history: list[dict],
    sources: list[Source],
    today: Optional[str] = None,
    places: str = "",
) -> list[dict]:
    """Rakit pesan final ke LLM: system berisi sumber, lalu riwayat, lalu pertanyaan."""
    today = today or date.today().isoformat()
    system = SYSTEM_PROMPT.format(
        today=today,
        context=build_context(sources),
        places=places,
    )

    messages: list[dict] = [{"role": "system", "content": system}]
    for item in history[-MAX_HISTORY:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|id|co|io|ai|gov|edu|info|me|dev|app|xyz|site|news|tv|ly|gg|sch|ac)"
    r"\b(?:/\S*)?",
    re.IGNORECASE,
)
_CITE_RE = re.compile(r"\[\d+\]")
_LIST_MARK_RE = re.compile(
    r"^[ \t]*(?:[-*•–—]|\d{1,3}[.)])[ \t]+", re.MULTILINE
)
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_SOURCE_PHRASE_RE = re.compile(
    r"(?i)\b(?:menurut\s+sumber(?:\s+[^\s,.;:]+)?|berdasarkan\s+(?:hasil\s+)?pencarian"
    r"|dari\s+hasil\s+pencarian|hasil\s+pencarian\s+menunjukkan"
    r"|sumber\s*:|referensi\s*:)[ \t]*(?:[,:][ \t]*)?"
)


def sanitize_answer(text: str) -> str:
    """Rapikan keluaran model sebelum sampai ke layar.

    Membuang tautan, nama domain, sitasi, penanda daftar, dan frasa yang
    menyebut proses pencarian. Teks yang sudah bersih dikembalikan apa adanya.
    """
    if not text:
        return ""

    cleaned = _URL_RE.sub("", text)
    cleaned = _DOMAIN_RE.sub("", cleaned)
    cleaned = _CITE_RE.sub("", cleaned)
    cleaned = _SOURCE_PHRASE_RE.sub("", cleaned)
    cleaned = _LIST_MARK_RE.sub("", cleaned)
    cleaned = _HEADING_RE.sub("", cleaned)
    cleaned = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), cleaned)
    cleaned = _ITALIC_RE.sub(r"\1", cleaned)
    cleaned = _CODE_RE.sub(r"\1", cleaned)

    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _short(exc: Exception, limit: int = 220) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:limit]


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many" in text


def _llm_error_message(exc: Exception) -> str:
    """Ubah error API jadi kalimat yang bisa ditindaklanjuti."""
    status = getattr(exc, "status_code", None)

    if status == 402 or "insufficient balance" in str(exc).lower():
        return (
            "Saldo akun penyedia LLM habis (kode 402). Isi ulang saldonya, "
            "lalu kirim ulang pertanyaannya."
        )
    if status == 401:
        return (
            "Kunci DeepSeek ditolak (401). Periksa DEEPSEEK_API_KEY di file .env, "
            "lalu restart server."
        )
    if status == 403:
        return "Kunci DeepSeek tidak punya izin untuk model ini (403). Periksa DEEPSEEK_MODEL di .env."
    if status == 429:
        return "DeepSeek sedang membatasi permintaan (429). Tunggu beberapa detik lalu coba lagi."
    if isinstance(status, int) and status >= 500:
        return f"Server DeepSeek sedang bermasalah ({status}). Coba lagi beberapa saat lagi."

    return f"LLM gagal menjawab: {_short(exc)}"


def _search_error_message(exc: Exception) -> str:
    """Pesan khusus untuk kegagalan Tavily yang paling sering terjadi."""
    text = str(exc).lower()

    if "432" in text or "quota" in text or "usage limit" in text:
        return (
            "Kuota pencarian Tavily bulan ini sudah habis. Tunggu bulan berikutnya, "
            "atau naikkan paket di https://app.tavily.com."
        )
    if "401" in text or "unauthorized" in text or "invalid api key" in text:
        return "Kunci Tavily ditolak. Periksa TAVILY_API_KEY di file .env, lalu restart server."

    return f"Pencarian web gagal: {_short(exc)}"


# --------------------------------------------------------------------------
# Unggahan: gambar dan audio
# --------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 3 * 1024 * 1024
ALLOWED_IMAGE = {"image/png", "image/jpeg", "image/webp", "image/gif"}
ALLOWED_AUDIO = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
}


def check_upload(mime: str, size: int, allowed: set) -> str:
    """Kembalikan pesan kesalahan, atau string kosong kalau berkas lolos."""
    mime = (mime or "").split(";")[0].strip().lower()
    if not mime:
        return "Jenis berkas tidak dikenal."
    if mime not in allowed:
        return f"Jenis berkas tidak didukung: {mime}"
    if size <= 0:
        return "Berkas kosong."
    if size > MAX_UPLOAD_BYTES:
        batas = MAX_UPLOAD_BYTES / (1024 * 1024)
        return f"Berkas {size / (1024 * 1024):.1f} MB, melebihi batas {batas:.0f} MB."
    return ""


def decode_upload(data_b64: str) -> bytes:
    """Urai base64 dari klien. Melempar ValueError kalau tidak sah."""
    cleaned = "".join((data_b64 or "").split())
    if "," in cleaned and cleaned.startswith("data:"):
        cleaned = cleaned.split(",", 1)[1]
    return base64.b64decode(cleaned, validate=True)


VISION_PROMPT = """Kamu melihat satu gambar yang dikirim pengguna.

Tulis satu kalimat pendek dalam Bahasa Indonesia yang bisa dipakai sebagai kata kunci pencarian untuk mencari informasi tentang gambar ini.

Sebutkan objek utama, merek atau tulisan yang terbaca, dan konteksnya kalau jelas terlihat. Jangan mengarang yang tidak tampak. Jangan menulis alamat situs atau nama domain. Balas hanya kalimat itu, tanpa pembuka."""


async def describe_image(mime: str, data_b64: str) -> str:
    """Ubah gambar jadi satu kalimat pencarian."""
    resp = await llm().chat.completions.create(
        model=vision_model_name(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data_b64}"},
                    },
                ],
            }
        ],
        temperature=0.2,
        max_tokens=200,
    )
    return sanitize_answer((resp.choices[0].message.content or "").strip())


STT_MODEL_DEFAULT = "whisper-large-v3-turbo"
STT_TIMEOUT_SECONDS = 60


def stt_ready() -> bool:
    return bool(
        os.environ.get("STT_BASE_URL", "").strip()
        and os.environ.get("STT_API_KEY", "").strip()
    )


async def transcribe_audio(data: bytes, filename: str, mime: str) -> str:
    """Kirim audio ke layanan transkripsi OpenAI-compatible dan ambil teksnya."""
    base = os.environ.get("STT_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("STT_API_KEY", "").strip()
    model = os.environ.get("STT_MODEL", STT_MODEL_DEFAULT)

    if not base or not key:
        raise RuntimeError(
            "Speech to text belum dikonfigurasi. Isi STT_BASE_URL dan STT_API_KEY di .env"
        )

    async with httpx.AsyncClient(timeout=STT_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename or "audio.webm", data, mime)},
            data={"model": model, "language": "id"},
        )

    if resp.status_code >= 400:
        raise RuntimeError(f"Layanan STT menolak: {resp.status_code} {resp.text[:160]}")

    payload = resp.json()
    return (payload.get("text") or "").strip()


REWRITE_SYSTEM = """Ubah pertanyaan terakhir pengguna menjadi satu query pencarian web yang berdiri sendiri dan spesifik.

- Selesaikan semua kata rujukan (dia, itu, harganya, yang tadi) memakai konteks percakapan.
- Pertahankan bahasa asli pengguna.
- Jangan menambah topik yang tidak ada di percakapan.
- Balas HANYA dengan query-nya, satu baris, tanpa tanda kutip, tanpa penjelasan."""


async def rewrite_query(message: str, history: list[dict]) -> str:
    """Jadikan pertanyaan lanjutan bisa dicari sendiri, misal 'kalau yang kedua?'."""
    transcript = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in history[-MAX_HISTORY:]
        if (m.get("content") or "").strip()
    )
    if not transcript:
        return message.strip()

    resp = await llm().chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM},
            {
                "role": "user",
                "content": f"Percakapan sejauh ini:\n{transcript}\n\nPertanyaan terakhir: {message}",
            },
        ],
        temperature=0,
        max_tokens=120,
    )
    raw = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return lines[0] if lines else message.strip()


async def web_search(
    query: str,
    max_results: int = MAX_RESULTS,
    days: Optional[int] = None,
) -> list[Source]:
    params = {
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": False,
    }
    if days:
        params["topic"] = "news"
        params["days"] = days

    try:
        raw = await searcher().search(**params)
    except Exception as exc:
        if not _is_rate_limit(exc):
            raise
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        raw = await searcher().search(**params)

    return map_results(raw)


async def answer_stream(
    message: str,
    history: Optional[list[dict]] = None,
    days: Optional[int] = None,
    location: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """Hasilkan kejadian: token* -> final -> done.

    Pencarian berjalan di balik layar. Klien hanya menerima teks jawaban,
    tanpa daftar sumber dan tanpa jejak proses pencarian.

    Kalau klien mengirim koordinat dan pertanyaannya menyangkut tempat, posisi
    itu dipakai untuk mencari tempat terdekat. Selain itu lokasi diabaikan,
    jadi pencarian biasa tidak melambat.
    """
    history = history or []
    message = (message or "").strip()
    if not message:
        yield {"event": "error", "data": {"message": "Pertanyaan kosong."}}
        return

    query = message
    if history:
        try:
            query = await rewrite_query(message, history)
        except Exception:
            query = message

    places_block = ""
    lat, lon = geo.valid_coords(location)
    if lat is not None and lon is not None and geo.is_local_question(query):
        try:
            area, places = await geo.local_context(lat, lon, query)
            accuracy = location.get("accuracy") if isinstance(location, dict) else None
            places_block = geo.format_places_block(area, places, accuracy)
            if area:
                query = f"{query} {area}"
        except Exception:
            places_block = ""

    try:
        sources = await web_search(query, days=days)
    except Exception as exc:
        yield {"event": "error", "data": {"message": _search_error_message(exc)}}
        return

    if not sources and not places_block:
        yield {"event": "token", "data": {"text": NOT_FOUND_TEXT}}
        yield {"event": "done", "data": {}}
        return

    collected: list[str] = []
    try:
        stream = await llm().chat.completions.create(
            model=model_name(),
            messages=build_messages(message, history, sources, places=places_block),
            stream=True,
            temperature=0.3,
            max_tokens=1200,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                collected.append(delta)
                yield {"event": "token", "data": {"text": delta}}
    except Exception as exc:
        yield {"event": "error", "data": {"message": _llm_error_message(exc)}}
        return

    raw = "".join(collected)
    cleaned = sanitize_answer(raw)
    if cleaned and cleaned != raw.strip():
        yield {"event": "final", "data": {"text": cleaned}}

    yield {"event": "done", "data": {}}
