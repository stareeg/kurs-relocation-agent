"""FR2-72: UTF-8 stdout/stderr на Windows до любых print из тестов.

Без этого `pytest` на дефолтной cp1251/866-консоли даёт кракозябры или UnicodeEncodeError
на русских assert-сообщениях. Старт-скрипты ставят PYTHONUTF8=1; этот файл страхует ручной
запуск `pytest` из «голой» консоли. Без DB-фикстур — только кодировка.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001 — поток перехвачен/закрыт
                pass
