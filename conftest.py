"""Pastikan akar proyek ada di sys.path saat pytest dijalankan.

Tanpa berkas ini, `pytest` polos tidak bisa menemukan modul main dan brain,
karena hanya `python -m pytest` yang menaruh direktori kerja di sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
