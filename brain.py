"""Inti mesin: tulis ulang query -> cari web -> susun prompt -> stream jawaban.

Tidak ada database. Setiap request membawa riwayatnya sendiri dari browser,
jadi proses ini sepenuhnya tanpa status.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

from openai import AsyncOpenAI
from tavily import AsyncTavilyClient

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

Di bawah ada bahan yang baru dikumpulkan dari web. Bahan itu satu-satunya dasar jawabanmu. Pengguna tidak melihat bahan itu dan tidak tahu ada pencarian, jadi jangan pernah merujuknya.

Cara menyusun jawaban:
1. Kalimat pertama langsung menjawab inti pertanyaan. Sisanya penjelasan yang mengalir.
2. Tulis sebagai paragraf naratif. Dilarang menyusun daftar bernomor, dilarang memakai bullet, dilarang memakai tanda hubung atau bintang di awal baris.
3. Dilarang menulis alamat situs, tautan, atau nama domain dalam bentuk apa pun.
4. Dilarang menulis frasa seperti "menurut sumber", "berdasarkan pencarian", "dari hasil pencarian", "sumber:", atau menyebut nomor sumber.
5. Dilarang mengarang angka, tanggal, nama, atau peristiwa. Kalau bahan tidak memuat jawabannya, jawab dengan satu atau dua kalimat sopan bahwa informasi itu belum tersedia, tanpa mengutip bahan mentah.
6. Kalau bahan saling bertentangan, sebutkan bahwa ada keterangan yang berbeda, tanpa menyebut asalnya.
7. Bahasa Indonesia. Dua sampai empat paragraf pendek, kecuali pertanyaannya memang menuntut lebih.

Bahan:
{context}"""


NOT_FOUND_TEXT = (
    "Maaf, informasi itu belum tersedia saat ini. Coba tanyakan dengan kata lain, "
    "atau sebutkan topiknya lebih spesifik."
)


def build_messages(
    message: str,
    history: list[dict],
    sources: list[Source],
    today: Optional[str] = None,
) -> list[dict]:
    """Rakit pesan final ke LLM: system berisi sumber, lalu riwayat, lalu pertanyaan."""
    today = today or date.today().isoformat()
    system = SYSTEM_PROMPT.format(today=today, context=build_context(sources))

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
# Jaringan
# --------------------------------------------------------------------------

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
) -> AsyncIterator[dict]:
    """Hasilkan kejadian: token* -> final -> done.

    Pencarian berjalan di balik layar. Klien hanya menerima teks jawaban,
    tanpa daftar sumber dan tanpa jejak proses pencarian.
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

    try:
        sources = await web_search(query, days=days)
    except Exception as exc:
        yield {"event": "error", "data": {"message": _search_error_message(exc)}}
        return

    if not sources:
        yield {"event": "token", "data": {"text": NOT_FOUND_TEXT}}
        yield {"event": "done", "data": {}}
        return

    collected: list[str] = []
    try:
        stream = await llm().chat.completions.create(
            model=model_name(),
            messages=build_messages(message, history, sources),
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
