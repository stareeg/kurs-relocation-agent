"""Бутстрап LangSmith-трассировки (задача 0.3).

LangChain включает трассировку по env-переменным (`LANGSMITH_TRACING`,
`LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`), которые langsmith SDK
читает напрямую из os.environ. Наш конфиг живёт в .env + secrets/, поэтому здесь мы
переносим значения из CoreSettings (и читаем ключ из файла secrets/) в os.environ.

Кастомная `OpenRouterChatModel` — обычный `BaseChatModel`, поэтому через
LangChain-каллбэки трассируется автоматически, без явного хендлера (подшаг 1).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from core.config import CoreSettings, get_settings
from core.platform.observability.logging import event

logger = logging.getLogger(__name__)


def _resolve_api_key(settings: CoreSettings) -> str:
    """Ключ: inline из .env, иначе первая значимая строка файла secrets/."""
    if settings.langsmith_api_key.strip():
        return settings.langsmith_api_key.strip()
    path = Path(settings.langsmith_api_key_path)
    if not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().strip("`").strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        # допускаем формат `LANGSMITH_API_KEY=...`
        if "=" in line and " " not in line.split("=", 1)[0]:
            line = line.split("=", 1)[1].strip().strip("`").strip('"').strip("'")
        return line
    return ""


@lru_cache
def configure_langsmith() -> bool:
    """Идемпотентно настроить env под LangSmith. Возвращает, включена ли трассировка.

    Вызывается лениво при первом создании чат-модели (get_chat_model) и может быть
    вызвана явно в lifespan API/бота.
    """
    settings = get_settings()
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    key = _resolve_api_key(settings)
    if not key:
        logger.warning(
            "LANGSMITH_TRACING=true, но ключ не найден (ни inline, ни в %s) — трассировка off",
            settings.langsmith_api_key_path,
        )
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    # Легаси-алиасы, которые читают некоторые версии langchain.
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    _quiet_langsmith_client_logger()
    event(logger, "ЗАПУСК", "LangSmith трассировка включена, проект=%s", settings.langsmith_project)
    return True


def _quiet_langsmith_client_logger() -> None:
    """Не пускать «не смог отправить трейс» в журнал.

    SDK LangSmith логирует каждый отказ доставки батча (в проде это `429 Rate limit exceeded`
    на бесплатном тарифе) на WARNING в свой логгер `langsmith.client` — 97 строк за трое суток,
    и это самая частая WARNING в витрине. Потерянный трейс не влияет ни на один пользовательский
    сценарий: LLM-вызов уже прошёл, трассировка — побочная телеметрия. Оставляем ERROR, чтобы
    настоящая поломка SDK не исчезла совсем.
    """
    logging.getLogger("langsmith.client").setLevel(logging.ERROR)


def langsmith_enabled() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
