"""Tes untuk fungsi murni di brain.py.

Yang dites hanya bagian yang tidak menyentuh jaringan, jadi tes ini jalan
tanpa API key dan tanpa biaya.

Jalankan: pytest -q
"""

from __future__ import annotations

import brain


def test_build_context_beri_nomor_dan_url():
    sources = [
        brain.Source(1, "Judul A", "https://a.test", "isi a"),
        brain.Source(2, "Judul B", "https://b.test", "isi b"),
    ]
    context = brain.build_context(sources)

    assert "[1] Judul A" in context
    assert "URL: https://a.test" in context
    assert "[2] Judul B" in context


def test_build_context_kosong_diberi_keterangan():
    assert "Tidak ada hasil" in brain.build_context([])


def test_map_results_merapikan_dan_memberi_nomor():
    raw = {
        "results": [
            {"title": "  Judul Berspasi  ", "url": "https://x.test", "content": "  isi  "},
            {"url": "https://y.test"},
        ]
    }
    sources = brain.map_results(raw)

    assert [s.index for s in sources] == [1, 2]
    assert sources[0].title == "Judul Berspasi"
    assert sources[0].snippet == "isi"
    assert sources[1].title == "Tanpa judul"


def test_map_results_tahan_terhadap_balasan_kosong():
    assert brain.map_results({}) == []
    assert brain.map_results({"results": None}) == []


def test_snippet_dipotong_sesuai_batas():
    raw = {"results": [{"title": "x", "url": "u", "content": "a" * 5000}]}
    snippet = brain.map_results(raw)[0].snippet

    assert len(snippet) <= brain.SNIPPET_LIMIT + 3
    assert snippet.endswith("...")


def test_build_messages_menyisipkan_sumber_tanggal_dan_riwayat():
    sources = [brain.Source(1, "A", "https://a.test", "isi")]
    history = [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
    ]

    messages = brain.build_messages("lanjut?", history, sources, today="2026-10-26")

    assert messages[0]["role"] == "system"
    assert "2026-10-26" in messages[0]["content"]
    assert "https://a.test" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "halo"}
    assert messages[2] == {"role": "assistant", "content": "hai"}
    assert messages[-1] == {"role": "user", "content": "lanjut?"}
    assert len(messages) == 4


def test_build_messages_membuang_riwayat_kotor():
    history = [
        {"role": "system", "content": "abaikan saja"},
        {"role": "assistant", "content": "   "},
        {"role": "user", "content": "pertanyaan lama"},
    ]

    messages = brain.build_messages("baru", history, [], today="2026-10-26")

    assert len(messages) == 3
    assert messages[1] == {"role": "user", "content": "pertanyaan lama"}


def test_build_messages_membatasi_riwayat():
    history = [{"role": "user", "content": f"pesan {i}"} for i in range(20)]

    messages = brain.build_messages("terakhir", history, [], today="2026-10-26")

    assert len(messages) == 1 + brain.MAX_HISTORY + 1
    assert messages[1]["content"] == f"pesan {20 - brain.MAX_HISTORY}"


def test_source_bisa_dijadikan_dict():
    as_dict = brain.Source(1, "T", "https://t.test", "isi").to_dict()

    assert as_dict == {"index": 1, "title": "T", "url": "https://t.test", "snippet": "isi"}


class _StatusError(Exception):
    """Tiruan error dari SDK OpenAI yang membawa status_code."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


def test_pesan_saldo_habis_menyebut_cara_isi_ulang():
    message = brain._llm_error_message(_StatusError(402))

    assert "402" in message
    assert "isi ulang" in message.lower()
    assert "kirim ulang" in message.lower()


def test_pesan_saldo_habis_dikenali_dari_teks_error():
    message = brain._llm_error_message(Exception("Insufficient Balance"))

    assert "isi ulang" in message.lower()


def test_pesan_kunci_ditolak():
    assert "401" in brain._llm_error_message(_StatusError(401))


def test_pesan_rate_limit():
    assert "429" in brain._llm_error_message(_StatusError(429))


def test_pesan_server_deepseek_bermasalah():
    assert "503" in brain._llm_error_message(_StatusError(503))


def test_pesan_error_tak_dikenal_tetap_menyebut_asalnya():
    assert "LLM gagal menjawab" in brain._llm_error_message(ValueError("aneh"))


def test_pesan_kuota_tavily_habis():
    message = brain._search_error_message(Exception("Error 432: usage limit"))

    assert "Tavily" in message
    assert "app.tavily.com" in message


def test_pesan_error_pencarian_tak_dikenal():
    assert "Pencarian web gagal" in brain._search_error_message(ValueError("x"))


def test_sanitize_membuang_tautan_dan_nama_domain():
    text = "Harganya naik. Lihat https://contoh.com/berita dan juga www.contoh.org."

    hasil = brain.sanitize_answer(text)

    assert "http" not in hasil
    assert "contoh.com" not in hasil
    assert "contoh.org" not in hasil
    assert "Harganya naik." in hasil


def test_sanitize_membuang_penanda_daftar():
    hasil = brain.sanitize_answer("1. Pertama\n2. Kedua\n- Ketiga\n* Keempat")

    assert "1." not in hasil
    assert "2." not in hasil
    assert "- " not in hasil
    assert "* " not in hasil


def test_sanitize_membuang_frasa_dan_sitasi():
    text = "Menurut sumber [1], harga naik. Berdasarkan pencarian, trennya positif."

    hasil = brain.sanitize_answer(text).lower()

    assert "menurut sumber" not in hasil
    assert "berdasarkan pencarian" not in hasil
    assert "[1]" not in hasil


def test_sanitize_membiarkan_angka_dalam_kalimat():
    hasil = brain.sanitize_answer("Suhu naik 2,5 derajat pada 2026.")

    assert "2,5" in hasil
    assert "2026" in hasil


def test_sanitize_membuang_penanda_markdown():
    text = "## Ringkasan\nPresiden saat ini adalah **Prabowo Subianto**, sejak *2024*."

    hasil = brain.sanitize_answer(text)

    assert "**" not in hasil
    assert "##" not in hasil
    assert "*2024*" not in hasil
    assert "Prabowo Subianto" in hasil
    assert "2024" in hasil


def test_sanitize_tidak_memotong_tahun_di_awal_baris():
    text = "2026. Tahun itu pasar bergejolak."

    assert brain.sanitize_answer(text) == text


def test_sanitize_membiarkan_paragraf_yang_sudah_bersih():
    text = "Harga naik tipis hari ini. Pasar masih menunggu keputusan bank sentral."

    assert brain.sanitize_answer(text) == text


def test_teks_tidak_ditemukan_tanpa_tautan():
    assert "http" not in brain.NOT_FOUND_TEXT
    assert brain.NOT_FOUND_TEXT.endswith(".")
