"""Kontrak streaming: apa yang boleh dan tidak boleh sampai ke browser.

Jaringan dipalsukan, jadi tes ini jalan tanpa API key dan tanpa biaya.
"""

from __future__ import annotations

import asyncio

import brain


class _FakeDelta:
    def __init__(self, text: str) -> None:
        self.content = text


class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.delta = _FakeDelta(text)


class _FakeChunk:
    def __init__(self, text: str) -> None:
        self.choices = [_FakeChoice(text)]


class _FakeStream:
    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces

    def __aiter__(self):
        return self._generate()

    async def _generate(self):
        for piece in self._pieces:
            yield _FakeChunk(piece)


class _FakeCompletions:
    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces

    async def create(self, **kwargs):
        return _FakeStream(self._pieces)


class _FakeClient:
    def __init__(self, pieces: list[str]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(pieces)})()


def _collect(message: str = "tanya"):
    async def run():
        return [event async for event in brain.answer_stream(message)]

    return asyncio.run(run())


def _fake_search(sources):
    async def search(query, max_results=5, days=None):
        return sources

    return search


def test_stream_tidak_mengirim_sumber_maupun_query(monkeypatch):
    monkeypatch.setattr(brain, "web_search", _fake_search([brain.Source(1, "T", "https://a.test", "isi")]))
    monkeypatch.setattr(brain, "llm", lambda: _FakeClient(["Harga naik."]))

    events = _collect()
    names = [event["event"] for event in events]

    assert "sources" not in names
    assert "query" not in names
    assert names[0] == "token"
    assert names[-1] == "done"


def test_stream_membersihkan_tautan_sitasi_dan_daftar(monkeypatch):
    monkeypatch.setattr(brain, "web_search", _fake_search([brain.Source(1, "T", "https://a.test", "isi")]))
    monkeypatch.setattr(
        brain,
        "llm",
        lambda: _FakeClient(
            [
                "1. Harga naik. ",
                "Lihat https://contoh.com/berita ",
                "dan [1] selesai.",
            ]
        ),
    )

    events = _collect()
    final = next(event["data"]["text"] for event in events if event["event"] == "final")

    assert "http" not in final
    assert "contoh.com" not in final
    assert "[1]" not in final
    assert "1. " not in final
    assert "Harga naik." in final


def test_stream_tanpa_hasil_memberi_kalimat_sopan(monkeypatch):
    monkeypatch.setattr(brain, "web_search", _fake_search([]))

    events = _collect()
    names = [event["event"] for event in events]
    text = "".join(event["data"].get("text", "") for event in events)

    assert "sources" not in names
    assert text == brain.NOT_FOUND_TEXT
    assert names[-1] == "done"


def test_stream_pertanyaan_kosong_ditolak():
    events = _collect("   ")

    assert events == [{"event": "error", "data": {"message": "Pertanyaan kosong."}}]
