"""Фоновое распознавание вложений-картинок.

Один kind в очереди A-20 (`platform.tasks`) на всю систему. Идемпотентный ключ строится по
`attachment_id`, не по `sha256`: до M4 (plans/multitenancy_gaps_2026_08_06.md §3.5) `sha256` был
уникален глобально, поэтому две загрузки одних байт всегда были одной строкой/одной задачей.
После M4 дедуп per-account (`unique(account_id, sha256)`) — одинаковые байты у ДВУХ разных
аккаунтов теперь дают ДВЕ разные строки, которым обеим нужен собственный разбор; ключ по id
сохраняет прежний эффект (повторная загрузка ОДНИМ аккаунтом → тот же id → та же задача) и не
схлопывает разбор между аккаунтами.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domains.assistant.attachments import repo
from core.domains.assistant.attachments.models import AttachmentAnalysis
from core.domains.assistant.events import publish_attachment_analyzed
from core.domains.assistant.llm import ATTACHMENT_READ
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event
from core.platform.tasks import enqueue_soon

logger = logging.getLogger(__name__)

#: Канон kind в очереди A-20 (регистрируется в core.app.background).
ATTACHMENT_READ_KIND = "attachment_read"

_USER_PROMPT = (
    "Перед тобой одно изображение, приложенное в чате карьерного копайлота. Разбери его по "
    "правилам из системного промпта."
)


def _idem_key(attachment_id: int) -> str:
    return f"{ATTACHMENT_READ_KIND}:{attachment_id}"


def schedule_attachment_read(attachment_id: int, *, account_id: int) -> None:
    """Поставить распознавание в очередь (upload и повторный запуск после кропа)."""
    enqueue_soon(
        ATTACHMENT_READ_KIND,
        payload={"attachment_id": attachment_id, "account_id": account_id},
        priority=50,
        idempotency_key=_idem_key(attachment_id),
        max_attempts=2,
        account_id=account_id,
    )
    event(
        logger,
        "ЗАДАЧА",
        "распознавание вложения в очереди: id=%s",
        attachment_id,
        attachment_id=str(attachment_id),
    )


async def run_attachment_read_from_payload(payload: Any) -> None:
    """Обработчик очереди `attachment_read` (регистрация — `core.app.background`)."""
    attachment_id = int((payload or {}).get("attachment_id") or 0)
    account_id = int((payload or {}).get("account_id") or 0)
    if not attachment_id or not account_id:
        raise ValueError("attachment_read: нужны attachment_id и account_id")
    await _run_attachment_read(attachment_id, account_id=account_id)


async def _run_attachment_read(attachment_id: int, *, account_id: int) -> None:
    attachment = await repo.get_data(attachment_id, account_id=account_id)
    if attachment is None:
        # Вложение убрал GC (не успел получить связку) между enqueue и запуском — не ошибка.
        event(
            logger,
            "ЗАДАЧА",
            "распознавание пропущено: вложение %s не найдено",
            attachment_id,
            level=logging.WARNING,
            attachment_id=str(attachment_id),
        )
        return

    try:
        analysis = await ports.llm().structured(
            ATTACHMENT_READ.name,
            user=_USER_PROMPT,
            schema=AttachmentAnalysis,
            images=[
                ports.ImageInput(
                    sha256=attachment.sha256, mime=attachment.mime, data=attachment.data
                )
            ],
        )
    except LlmError as exc:
        await repo.set_analysis(
            attachment_id, account_id=account_id, status="failed", analysis=None
        )
        publish_attachment_analyzed(attachment_id=attachment_id, kind="")
        event(
            logger,
            "ОШИБКА",
            "распознавание вложения %s упало: %s",
            attachment_id,
            exc,
            level=logging.ERROR,
            attachment_id=str(attachment_id),
        )
        return

    await repo.set_analysis(attachment_id, account_id=account_id, status="ready", analysis=analysis)
    publish_attachment_analyzed(attachment_id=attachment_id, kind=analysis.kind)
    event(
        logger,
        "ЗАДАЧА",
        "вложение %s распознано: kind=%s",
        attachment_id,
        analysis.kind,
        attachment_id=str(attachment_id),
    )


__all__ = [
    "ATTACHMENT_READ_KIND",
    "run_attachment_read_from_payload",
    "schedule_attachment_read",
]
