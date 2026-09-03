"""Guard: какие HTTP-запросы вообще доезжают до витрины логов и бандла.

Порог `QueueLogHandler` — INFO, поэтому DEBUG остаётся только в файле на сервере и в архив
пользователю не попадает. До этой правки ВСЁ, кроме 5xx, писалось в DEBUG: в бандле не было ни
одного действия человека и ни одного 4xx — «кнопка не сработала» разбирать было не по чему.
Тест фиксирует правило, чтобы уровень не откатили обратно «за компанию» с рефакторингом.
"""

from __future__ import annotations

import logging

from api.main import _http_log_level


def test_server_error_is_error_level() -> None:
    assert _http_log_level(method="GET", status=500, duration_ms=10) == logging.ERROR
    assert _http_log_level(method="POST", status=503, duration_ms=10) == logging.ERROR


def test_client_error_is_warning_and_reaches_bundle() -> None:
    """401/404/422 — отказ пользователю; в архиве он обязан быть виден."""
    for status in (400, 401, 404, 422, 429):
        assert _http_log_level(method="GET", status=status, duration_ms=10) == logging.WARNING


def test_mutations_are_info_reads_are_debug() -> None:
    """Лента «что человек делал» = успешные мутации. Успешные GET — поллинг, в витрину не идут."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _http_log_level(method=method, status=200, duration_ms=10) == logging.INFO
    assert _http_log_level(method="GET", status=200, duration_ms=10) == logging.DEBUG
    assert _http_log_level(method="HEAD", status=204, duration_ms=10) == logging.DEBUG


def test_slow_success_is_info() -> None:
    """«Всё грузится вечно» должно быть с чем сопоставить — медленный ответ попадает в витрину."""
    from api.main import _SLOW_REQUEST_MS

    assert _http_log_level(method="GET", status=200, duration_ms=_SLOW_REQUEST_MS) == logging.INFO
    assert _http_log_level(method="GET", status=200, duration_ms=_SLOW_REQUEST_MS - 1) == (
        logging.DEBUG
    )
