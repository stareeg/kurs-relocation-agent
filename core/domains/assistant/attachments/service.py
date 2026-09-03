"""Сервис вложений: приём файла (картинки — Э0-3; текстовые документы txt/md/pdf/docx —
2026-08-11), мета, кадрирование.

Персист обязателен — картинка без сохранённой строки в `attachments` не может считаться
загруженной (тот же принцип, что у `assistant.prep_chat`: чат без записи молча теряет реплики,
см. `core/app/scenarios/prep_chat.py`). Любой сбой Postgres здесь — `StorageUnavailable`, а не
тихая деградация. Формат/размер файла — это `InvalidInput` (вход не годится), а не сбой хранилища.

`_MAX_SIDE_PX`/`_THUMB_PX` дублируют дефолты §7 плана (`ATTACHMENT_MAX_SIDE_PX`/
`ATTACHMENT_THUMB_PX`); настройками из `.env`/`app_settings` они станут при подключении роутера
(Э0-4/§7) — здесь сознательно нет импорта `core.platform.config`, чтобы не тащить конфиг в
доменный слой раньше, чем он реально нужен.

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): каждая функция требует `account_id` —
`attachments` больше не одна таблица на всю систему, `NotFound` от `repo` для чужого id закрывает
IDOR («перебор id выдаёт чужие скриншоты»), а не только роутер сверху.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from core.domains.assistant.attachments import repo
from core.domains.assistant.attachments.models import (
    Attachment,
    AttachmentAnalysis,
    AttachmentMeta,
    AttachmentRoute,
)
from core.domains.assistant.attachments.tasks import schedule_attachment_read
from core.kernel import ports
from core.kernel.errors import (
    DomainError,
    InvalidInput,
    NotFound,
    StorageUnavailable,
    Unprocessable,
)
from core.kernel.text.extract import (
    DOCUMENT_MIME_EXTRACTORS,
    DocumentExtractError,
    extract_document_text,
)
from core.kernel.text.untrusted import wrap_untrusted
from core.platform.images import crop as crop_image
from core.platform.images import decode_and_normalize, make_thumb

logger = logging.getLogger(__name__)

_NO_PG = "Postgres недоступен — вложение не сохранено"
_MAX_SIDE_PX = 1568
_THUMB_PX = 512

# Расширение → mime документа — фолбэк, когда браузер прислал generic/пустой content-type
# (частый случай для .md: ОС не всегда знает эту ассоциацию).
_DOCUMENT_EXT_MIME: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _resolve_document_mime(content_type: str | None, filename: str | None) -> str | None:
    """Документ (txt/md/pdf/docx) или `None` — тогда вызывающий пробует картиночный путь.

    Content-type браузера приоритетнее, но не всегда надёжен (generic `application/octet-stream`,
    пустая строка) — расширение имени файла подстраховывает.
    """
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in DOCUMENT_MIME_EXTRACTORS:
        return ct
    ext = Path(filename or "").suffix.lower()
    return _DOCUMENT_EXT_MIME.get(ext)


async def store_upload(
    raw: bytes,
    *,
    account_id: int,
    content_type: str | None = None,
    filename: str | None = None,
) -> AttachmentMeta:
    """Байты файла → нормализация (Pillow держит GIL, поэтому `asyncio.to_thread`) → upsert.

    `content_type`/`filename` (2026-08-11, текстовые вложения) — только для маршрутизации
    txt/md/pdf/docx на текстовый путь `_store_document_upload`; без совпадения — прежний
    картиночный путь (Pillow сам решает, что за формат, как и раньше).

    `UnsupportedImageError` пробрасывается как есть — это невалидный вход (роутер/Э0-4 превратит
    его в 400), а не сбой хранилища.
    """
    document_mime = _resolve_document_mime(content_type, filename)
    if document_mime is not None:
        return await _store_document_upload(
            raw, account_id=account_id, mime=document_mime, filename=filename
        )

    normalized = await asyncio.to_thread(decode_and_normalize, raw, max_side=_MAX_SIDE_PX)
    thumb = await asyncio.to_thread(make_thumb, normalized.data, max_side=_THUMB_PX)
    try:
        meta = await repo.upsert_attachment(
            account_id=account_id,
            sha256=normalized.sha256,
            mime=normalized.mime,
            width=normalized.width,
            height=normalized.height,
            data=normalized.data,
            thumb=thumb.data,
            thumb_width=thumb.width,
            thumb_height=thumb.height,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → 503, вложение не теряется молча
        logger.error("attachments: загрузка не сохранена (нет PG?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    # `pending` — либо новая строка, либо повторный upload той же картинки, чью первую задачу
    # ещё не подхватил воркер; `ready`/`failed`/`skipped` — тот же sha256 уже разобран, второй
    # LLM-вызов не нужен (идемпотентный ключ ниже и так бы его схлопнул, но зачем enqueue впустую).
    if meta.analysis_status == "pending":
        schedule_attachment_read(meta.id, account_id=account_id)
    return meta


def _default_document_title(mime: str) -> str:
    for ext, m in _DOCUMENT_EXT_MIME.items():
        if m == mime:
            return f"Документ{ext}"
    return "Документ"


async def _store_document_upload(
    raw: bytes, *, account_id: int, mime: str, filename: str | None
) -> AttachmentMeta:
    """Текстовое вложение (txt/md/pdf/docx): текст извлекается сразу (не LLM, не фоновая задача)
    — `analysis_status='ready'` синхронно с ответом на upload. Нет width/height/thumb (не
    картинка) — 0/пустые байты, схема `attachments` их и так допускает как обычные значения,
    не null (миграция не нужна)."""
    try:
        text = await asyncio.to_thread(extract_document_text, raw, mime)
    except DocumentExtractError as exc:
        raise InvalidInput(str(exc)) from exc
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        meta = await repo.upsert_attachment(
            account_id=account_id,
            sha256=sha256,
            mime=mime,
            width=0,
            height=0,
            data=raw,
            thumb=b"",
            thumb_width=0,
            thumb_height=0,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → 503, вложение не теряется молча
        logger.error("attachments: документ не сохранён (нет PG?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    if meta.analysis_status != "pending":
        return meta  # дедуп по (account_id, sha256) — тот же файл уже разобран
    title = (filename or "").strip() or _default_document_title(mime)
    analysis = AttachmentAnalysis(
        kind="document", title=title, summary="", text=text, confidence=1.0
    )
    await repo.set_analysis(meta.id, account_id=account_id, status="ready", analysis=analysis)
    return meta.model_copy(update={"analysis_status": "ready", "analysis": analysis})


async def get_meta(attachment_id: int, *, account_id: int) -> AttachmentMeta:
    """Мета вложения. Нет строки/чужая → `NotFound`; нет PG → `StorageUnavailable`."""
    try:
        meta = await repo.get_meta(attachment_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        raise StorageUnavailable(_NO_PG) from exc
    if meta is None:
        raise NotFound("Вложение не найдено")
    return meta


async def get_attachment(attachment_id: int, *, account_id: int) -> Attachment:
    """Полная строка с байтами — отдача `GET /api/attachments/{id}[/thumb]` (Э0-4)."""
    try:
        attachment = await repo.get_data(attachment_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        raise StorageUnavailable(_NO_PG) from exc
    if attachment is None:
        raise NotFound("Вложение не найдено")
    return attachment


async def crop_attachment(
    attachment_id: int, box: tuple[float, float, float, float], *, account_id: int
) -> AttachmentMeta:
    """Кадрирование не портит оригинал — новая строка с `derived_from` (плана).

    `box` — доли `(x, y, w, h)` 0..1 относительно исходной картинки; пустой после клампа к
    границам → `InvalidInput` (`core.platform.images.crop` бросает `ValueError`).
    """
    try:
        source = await repo.get_data(attachment_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        raise StorageUnavailable(_NO_PG) from exc
    if source is None:
        raise NotFound("Вложение не найдено")

    try:
        cropped = await asyncio.to_thread(crop_image, source.data, box)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    thumb = await asyncio.to_thread(make_thumb, cropped.data, max_side=_THUMB_PX)

    try:
        meta = await repo.upsert_attachment(
            account_id=account_id,
            sha256=cropped.sha256,
            mime=cropped.mime,
            width=cropped.width,
            height=cropped.height,
            data=cropped.data,
            thumb=thumb.data,
            thumb_width=thumb.width,
            thumb_height=thumb.height,
            derived_from=attachment_id,
            crop={"x": box[0], "y": box[1], "w": box[2], "h": box[3]},
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → 503, кроп не теряется молча
        logger.error("attachments: кроп не сохранён (нет PG?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    # Пиксели изменились — старый разбор источника не годится для кропа (плана).
    if meta.analysis_status == "pending":
        schedule_attachment_read(meta.id, account_id=account_id)
    return meta


async def link_to_hr_message(
    message_id: int, attachment_ids: list[int], *, account_id: int
) -> None:
    """Привязать вложения текущего HR-сообщения к его строке (Э2-5): черновик = отсутствие
    связки, связка появляется только в момент отправки."""
    if not attachment_ids:
        return
    try:
        await repo.link_hr_message_attachments(message_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки не сохранены (message_id=%s): %s", message_id, exc)
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_hr_messages(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких HR-реплик одной ленты — для проекции ленты в API/промпт (Э2-5)."""
    try:
        return await repo.load_hr_message_attachments(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def link_to_debrief(debrief_id: int, attachment_ids: list[int], *, account_id: int) -> None:
    """Привязать вложения к сохранённому разбору собеса (Э4-4) — картинки уже загружены до
    отправки, разбор ещё не имел id; связка появляется, как только он появился."""
    if not attachment_ids:
        return
    try:
        await repo.link_debrief_attachments(debrief_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error(
            "attachments: связки разбора не сохранены (debrief_id=%s): %s", debrief_id, exc
        )
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_debriefs(
    debrief_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких разборов — карточка разбора и история (Э4-4)."""
    try:
        return await repo.load_debrief_attachments(debrief_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: вложения разборов не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def link_to_prep_chat_message(
    message_id: int, attachment_ids: list[int], *, account_id: int
) -> None:
    """Привязать вложения текущей реплики чата подготовки (Э2-5) — своя пара функций,
    не общий `link_to_message`: `prep_chat_message_attachments` уже несёт `account_id`."""
    if not attachment_ids:
        return
    try:
        await repo.link_prep_chat_attachments(message_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error(
            "attachments: связки чата подготовки не сохранены (message_id=%s): %s", message_id, exc
        )
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_prep_chat_messages(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата подготовки — для проекции ленты в API/промпт (Э2-5)."""
    try:
        return await repo.load_prep_chat_attachments(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки чата подготовки не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def link_to_market_chat_message(
    message_id: int, attachment_ids: list[int], *, account_id: int
) -> None:
    """Привязать вложения текущей реплики чата «Рынка» (Заход 6, п.7) — своя пара функций,
    не общий `link_to_message`: `market_chat_message_attachments` уже несёт `account_id`."""
    if not attachment_ids:
        return
    try:
        await repo.link_market_chat_attachments(message_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error(
            "attachments: связки чата рынка не сохранены (message_id=%s): %s", message_id, exc
        )
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_market_chat_messages(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата «Рынка» — для проекции ленты в API/промпт."""
    try:
        return await repo.load_market_chat_attachments(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки чата рынка не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def link_to_resume_chat_message(
    message_id: int, attachment_ids: list[int], *, account_id: int
) -> None:
    """Привязать вложения текущей реплики чата по резюме (паритет с чатом «Рынка», миграция 0120)
    — своя пара функций, не общий `link_to_message`: `resume_chat_message_attachments` несёт
    `account_id`."""
    if not attachment_ids:
        return
    try:
        await repo.link_resume_chat_attachments(message_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error(
            "attachments: связки чата по резюме не сохранены (message_id=%s): %s", message_id, exc
        )
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_resume_chat_messages(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата по резюме — для проекции ленты в API."""
    try:
        return await repo.load_resume_chat_attachments(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки чата по резюме не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def link_to_offers_chat_message(
    message_id: int, attachment_ids: list[int], *, account_id: int
) -> None:
    """Привязать вложения текущей реплики чата «Офферы» — своя пара функций,
    не общий `link_to_message`: `offers_chat_message_attachments` несёт `account_id`."""
    if not attachment_ids:
        return
    try:
        await repo.link_offers_chat_attachments(message_id, attachment_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error(
            "attachments: связки чата офферов не сохранены (message_id=%s): %s", message_id, exc
        )
        raise StorageUnavailable(_NO_PG) from exc


async def load_for_offers_chat_messages(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата «Офферы» — для проекции ленты в API."""
    try:
        return await repo.load_offers_chat_attachments(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring модуля
        logger.error("attachments: связки чата офферов не загружены: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def wait_ready(
    attachment_ids: Sequence[int],
    *,
    account_id: int,
    timeout_s: float = 20.0,
    poll_interval_s: float = 0.5,
) -> list[AttachmentMeta]:
    """Дождаться распознавания вложений (Э4-1, режимы-парсеры: HR-импорт/`parse_external`).

    Текст переписки там берётся из `analysis`, поэтому картинка должна быть разобрана ДО передачи
    в текстовый конвейер — в отличие от вложений диалога (Э2/Э3), которые уходят в модель как есть
    без ожидания. Пока владелец печатает/жмёт «Импортировать» — распознавание почти всегда уже
    готово (плана: обычно 1.5-3с), таймаут — редкий путь, не норма.
    """
    ids = list(dict.fromkeys(attachment_ids))
    if not ids:
        return []
    deadline = time.monotonic() + timeout_s
    ready: dict[int, AttachmentMeta] = {}
    pending = set(ids)
    while True:
        for attachment_id in list(pending):
            meta = await get_meta(attachment_id, account_id=account_id)
            if meta.analysis_status != "pending":
                ready[attachment_id] = meta
                pending.discard(attachment_id)
        if not pending:
            return [ready[i] for i in ids]
        if time.monotonic() >= deadline:
            raise Unprocessable("Скриншот ещё распознаётся, подождите пару секунд и повторите")
        await asyncio.sleep(poll_interval_s)


def resolve_attachment_route(
    analysis: AttachmentAnalysis | None, override: AttachmentRoute | None = None
) -> AttachmentRoute:
    """Ветка вложения в режимах-парсерах (плана, Э4-3) — чистая функция, без побочных эффектов.

    `override` — ярлык-переключатель на чипе (`RouteBadge`, композер), которым владелец правит
    угадку классификатора одним кликом; он побеждает `kind`. Без override — тот же автоматический
    выбор, что был раньше: `correspondence` только при `kind == "correspondence"`, иначе `material`
    (включая ещё не распознанные/упавшие вложения).
    """
    if override is not None:
        return override
    if analysis is not None and analysis.kind == "correspondence":
        return "correspondence"
    return "material"


def correspondence_dump(analysis: AttachmentAnalysis | None, route: AttachmentRoute) -> str:
    """Текст со скрина переписки для текстового дампа (режимы-парсеры, Этап 4 плана: HR-импорт
    Э4-1, разбор внешнего ИИ Э4-2) — реплики по авторам, если распознаны, иначе дословный текст.

    `route` (уже разрешённый `resolve_attachment_route`, с учётом возможного переопределения
    владельцем) `!= "correspondence"` → пусто: картинка не годится для текстового конвейера,
    вызывающая сторона должна отправить её как вложение диалога вместо текста.
    """
    if route != "correspondence" or analysis is None:
        return ""
    if analysis.turns:
        return "\n".join(
            f"{t.speaker.strip()}: {t.text.strip()}" for t in analysis.turns if t.text.strip()
        )
    return analysis.text.strip()


async def load_llm_context(
    attachment_ids: Sequence[int], *, account_id: int
) -> tuple[list[ports.ImageInput], str]:
    """Вложения ТЕКУЩЕЙ реплики для LLM-вызова (правило истории, §3 плана — инлайном уходят
    только вложения текущего сообщения): картинки — отдельным списком для мультимодального
    вызова (`images=`), текстовые документы (txt/md/pdf/docx, 2026-08-11) — одним текстовым
    блоком с спотлайтингом (недоверенный ввод), вызывающий склеивает его в `dynamic_tail`/user.

    Best-effort по каждому id отдельно: вложение, которое GC успел убрать между paste и
    «Отправить», чужой/устаревший id (IDOR-попытка) — молча пропускаем, не валим весь ответ чата
    из-за одного вложения, и не подтверждаем/опровергаем существование чужого id.
    """
    images: list[ports.ImageInput] = []
    doc_blocks: list[str] = []
    for attachment_id in attachment_ids:
        try:
            attachment = await get_attachment(attachment_id, account_id=account_id)
        except DomainError as exc:
            logger.warning("attachments: вложение %s недоступно для LLM: %s", attachment_id, exc)
            continue
        if attachment.mime.startswith("image/"):
            images.append(
                ports.ImageInput(
                    sha256=attachment.sha256, mime=attachment.mime, data=attachment.data
                )
            )
            continue
        analysis = attachment.analysis
        if analysis is None or not analysis.text.strip():
            continue
        title = analysis.title.strip() or "Документ"
        doc_blocks.append(f"### {title}\n\n{wrap_untrusted(analysis.text, source='attachment')}")
    doc_text = "\n\n".join(doc_blocks)
    return images, doc_text


__all__ = [
    "correspondence_dump",
    "crop_attachment",
    "get_attachment",
    "get_meta",
    "link_to_debrief",
    "link_to_hr_message",
    "link_to_market_chat_message",
    "link_to_offers_chat_message",
    "link_to_prep_chat_message",
    "link_to_resume_chat_message",
    "load_for_debriefs",
    "load_for_hr_messages",
    "load_for_market_chat_messages",
    "load_for_offers_chat_messages",
    "load_for_prep_chat_messages",
    "load_for_resume_chat_messages",
    "load_llm_context",
    "resolve_attachment_route",
    "store_upload",
    "wait_ready",
]
