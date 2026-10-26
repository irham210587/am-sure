"""Server HTTP: satu endpoint streaming, sisanya file statis.

Jalankan: uvicorn main:app --reload
Buka   : http://127.0.0.1:8000
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

import brain  # noqa: E402  (dimuat setelah .env terbaca)

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="Iam Sure",
    description="Bot pencarian real-time tanpa database.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

ACCESS_KEY = os.environ.get("APP_ACCESS_KEY", "").strip()


async def require_access(x_access_key: Optional[str] = Header(default=None)) -> None:
    """Kalau APP_ACCESS_KEY di-set, permintaan wajib membawa header yang cocok.

    Kosongkan APP_ACCESS_KEY saat mengembangkan di komputer sendiri; penjaga
    ini otomatis tidak aktif.
    """
    if not ACCESS_KEY:
        return
    if not x_access_key or not hmac.compare_digest(x_access_key, ACCESS_KEY):
        raise HTTPException(status_code=401, detail="Kunci akses salah atau belum diisi.")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list)
    days: Optional[int] = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


PLACEHOLDER_MARKERS = ("isi-di-sini", "ISI-KUNCI")


def is_real_key(value: Optional[str]) -> bool:
    """Kunci dianggap terisi hanya kalau ada isinya dan bukan nilai contoh."""
    text = (value or "").strip()
    return bool(text) and not any(marker in text for marker in PLACEHOLDER_MARKERS)


@app.get("/api/health")
async def health() -> dict:
    deepseek = is_real_key(os.environ.get("DEEPSEEK_API_KEY"))
    tavily = is_real_key(os.environ.get("TAVILY_API_KEY"))
    return {
        "ok": deepseek and tavily,
        "deepseek_key": deepseek,
        "tavily_key": tavily,
        "model": brain.model_name(),
        "access_required": bool(ACCESS_KEY),
    }


@app.post("/api/chat", dependencies=[Depends(require_access)])
async def chat(body: ChatRequest) -> StreamingResponse:
    history = [m.model_dump() for m in body.history]

    async def generate():
        try:
            async for item in brain.answer_stream(body.message, history, days=body.days):
                yield sse(item["event"], item["data"])
        except Exception as exc:  # jaring terakhir: stream tidak boleh mati diam-diam
            yield sse("error", {"message": f"Kesalahan tak terduga: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
