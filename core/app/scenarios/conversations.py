"""Разговор по вакансии: единая лента HR-переписки и уточняющего чата.

Кросс-доменный сценарий: тред и реплики — `pipeline`, статус/компания/enrichment вакансии —
`opportunities`, ближайшие этапы — `preparation`. Раньше эта сборка жила в
`api/routers/assistant/conversations.py`; домены по-прежнему не знают друг о друге, склейка —
здесь.

Деградация сохранена дословно: чтение без Postgres отдаёт пустой разговор (вкладка не падает),
запись без Postgres — `StorageUnavailable` (503), потому что молча потерять реплику нельзя.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from core.domains.assistant.attachments.models import AttachmentMeta, AttachmentRoute
from core.domains.opportunities.jobs import Job
from core.domains.pipeline.hr_threads import HrMessage, HrThread
from core.kernel.errors import StorageUnavailable, Unprocessable

logger = logging.getLogger(__name__)

NO_STORE = "Хранилище разговоров недоступно"

# Порог тишины для блока «Напомнить» — держать синхронно с ChatsSidebar.tsx
# REMINDER_THRESHOLD_DAYS (владелец один, отдельная настройка избыточна).
ATTENTION_REMINDER_DAYS = 4
# «Ответить» — не орём сразу после письма HR: свежее сообщение и так видно в Чатах.
# 2 часа — пауза «успеть ответить самому», дальше это уже очередь дня, а не спам.
ATTENTION_REPLY_COOLDOWN_HOURS = 2
ATTENTION_STRONG_SCORE = 80
ATTENTION_STRONG_WINDOW_DAYS = 30
ATTENTION_LIMIT = 5

_SORT_EPOCH = datetime.min.replace(tzinfo=UTC)


class ConversationView(BaseModel):
    """Канонический разговор вакансии: тред + лента реплик + ссылка на HR.

    message_attachments (Э2-5) — картинки-вложения по message_id; отдельный словарь, а не поле на
    `HrMessage` (домен `pipeline` ничего не знает о домене `assistant.attachments` — склейка
    кросс-доменных данных живёт здесь, в сценарии, как и у остальных полей `ConversationView`).
    """

    vacancy_id: str
    thread: HrThread | None = None
    messages: list[HrMessage] = []
    hr_link: str = ""
    message_attachments: dict[int, list[AttachmentMeta]] = Field(default_factory=dict)


class OutreachResult(BaseModel):
    """Итог HR-first контакта: заведённая вакансия + был ли скоринг."""

    vacancy_id: str
    scored: bool = False
    conversation: ConversationView


class ImportResult(BaseModel):
    """Итог разбора вставленного дампа переписки.

    `added_kinds` — типы именно новых реплик: фоновый пересчёт запускается только если в дампе
    были слова рекрутера, а не потому что они когда-то были в ленте.
    `unrecognized_attachment_ids` (Э4-1) — картинки из запроса, распознанные НЕ как переписка
    (`analysis.kind != "correspondence"`, разбор упал/пропущен) — в дамп они не попали; фронт
    предлагает приложить их как вложение диалога вместо импорта.
    """

    added: int = 0
    added_kinds: list[str] = []
    unrecognized_attachment_ids: list[int] = []
    conversation: ConversationView


class UpcomingStage(BaseModel):
    """Ближайший этап собеса для витрины дня."""

    vacancy_id: str
    company: str = ""
    stage_type: str
    scheduled_at: datetime | None = None
    format: str | None = None


class AttentionView(BaseModel):
    """Витрина дня «Чатов»: ответить / напомнить / скоро собес / свежие сильные."""

    reply: list[HrThread] = []
    remind: list[HrThread] = []
    upcoming: list[UpcomingStage] = []
    strong_unapplied: list[Job] = []


# --------------------------------------------------------------------------- чтение


async def load_conversation(vacancy_id: str, *, account_id: int) -> ConversationView:
    """Разговор вакансии без создания треда. Нет PG/разговора → пустой вид (thread=None)."""
    from core.domains.pipeline.hr_threads import get_primary_thread, list_messages

    try:
        hr_link = await _hr_link(vacancy_id, account_id=account_id)
        thread = await get_primary_thread(vacancy_id, account_id=account_id)
        if thread is None or thread.id is None:
            return ConversationView(vacancy_id=vacancy_id, hr_link=hr_link)
        messages = await list_messages(thread.id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пусто, дровер не падает
        logger.debug("conversations: чтение недоступно (%s): %s", vacancy_id, exc)
        return ConversationView(vacancy_id=vacancy_id)
    return ConversationView(
        vacancy_id=vacancy_id,
        thread=await _sanitize_suggestion(thread, account_id=account_id),
        messages=list(messages),
        hr_link=hr_link,
        message_attachments=await _load_message_attachments(
            [m.id for m in messages if m.id is not None], account_id=account_id
        ),
    )


async def _load_message_attachments(
    message_ids: list[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения-картинки этих реплик (Э2-5) — нет PG/таблицы → лента без вложений, не 500."""
    if not message_ids:
        return {}
    try:
        from core.domains.assistant.attachments.service import load_for_hr_messages

        return await load_for_hr_messages(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — best-effort, как остальные блоки этого вида
        logger.debug("conversations: вложения сообщений недоступны: %s", exc)
        return {}


async def load_attention(*, account_id: int) -> AttentionView:
    """Четыре SQL-агрегата без LLM: первый экран открывается на каждый заход."""
    threads, hide = await _attention_scope(account_id=account_id)
    return AttentionView(
        reply=_reply_bucket(threads),
        remind=_remind_bucket(threads),
        upcoming=await _upcoming_bucket(account_id=account_id, hide=hide),
        strong_unapplied=await _strong_unapplied_bucket(account_id=account_id, hide=hide),
    )


async def suggest_attach(
    text: str,
    *,
    company: str | None = None,
    vacancy_url: str | None = None,
    account_id: int,
) -> list:
    """Кандидаты на привязку дампа/черновика к известной вакансии (детерминированно, без LLM).

    Пусто — ничего подходящего; ровно один — чип; два и больше — пикер (silent pick запрещён).
    """
    from core.domains.pipeline.vacancy_attach_suggest import suggest_vacancy_attach

    try:
        found = await suggest_vacancy_attach(
            text, company=company or "", vacancy_url=vacancy_url or "", account_id=account_id
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → без предложения, экран не падает
        logger.debug("conversations: suggest-attach недоступен: %s", exc)
        return []
    return list(found.candidates)


# --------------------------------------------------------------------------- запись


async def create_outreach(
    *,
    company: str,
    position: str,
    contact_name: str,
    hr_link: str,
    vacancy_url: str,
    initial_text: str,
    vacancy_text: str,
    first_contact_at=None,
    account_id: int,
) -> OutreachResult:
    """Новая вакансия из HR-first контакта: job в воронке + тред + опциональный скоринг."""
    from core.domains.pipeline.outreach import create_outreach_vacancy

    if not any(
        p.strip()
        for p in (
            company,
            position,
            contact_name,
            hr_link,
            vacancy_url,
            initial_text,
            vacancy_text,
        )
    ):
        raise Unprocessable(
            "Укажите текст вакансии, компанию, ссылку на вакансию или текст первого сообщения HR"
        )

    try:
        vacancy_id, scored = await create_outreach_vacancy(
            company=company,
            position=position,
            contact_name=contact_name,
            hr_link=hr_link,
            vacancy_url=vacancy_url,
            initial_text=initial_text,
            vacancy_text=vacancy_text,
            first_contact_at=first_contact_at,
            account_id=account_id,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning("conversations: outreach не создан (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc

    conversation = await load_conversation(vacancy_id, account_id=account_id)
    if conversation.thread is None:
        raise StorageUnavailable(NO_STORE)
    return OutreachResult(vacancy_id=vacancy_id, scored=scored, conversation=conversation)


async def open_conversation(vacancy_id: str, *, account_id: int) -> ConversationView:
    """FR2-87: закрепить открытие уже известной вакансии как настоящий разговор.

    Клик по чипу «Привязать к …?» без вставленного дампа раньше не писал в PG вовсе — заводился
    только вид разговора в памяти фронта. Тред не появлялся ни в `hr_threads`, ни в списке слева
    (`list_recent_threads` его не видит), а уход со вкладки без единого сообщения обнулял всё —
    приходилось заново проходить «Добавить вакансию» (баг привязки без дампа, 2026-08-12)."""
    from core.domains.pipeline.hr_threads import get_or_create_thread

    try:
        await get_or_create_thread(
            vacancy_id,
            company=await _company(vacancy_id, account_id=account_id),
            account_id=account_id,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning("conversations: открытие разговора не удалось (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc
    return await load_conversation(vacancy_id, account_id=account_id)


async def add_conversation_message(
    vacancy_id: str, *, kind: str, body: str, sent_at=None, account_id: int
) -> ConversationView:
    """Добавить реплику (HR-сообщение / своё в HR / в ассистента). Нет PG → 503."""
    from core.domains.pipeline.hr_threads import add_message, get_or_create_thread

    try:
        thread = await get_or_create_thread(
            vacancy_id,
            company=await _company(vacancy_id, account_id=account_id),
            account_id=account_id,
        )
        assert thread.id is not None
        await add_message(
            HrMessage(thread_id=thread.id, kind=kind, body=body, sent_at=sent_at),
            account_id=account_id,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning("conversations: реплика не добавлена (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc
    return await load_conversation(vacancy_id, account_id=account_id)


async def delete_conversation_message(
    vacancy_id: str, message_id: int, *, account_id: int
) -> ConversationView:
    """Удалить одну реплику ленты (выделение → Удалить во фронте).

    Проверяем, что реплика принадлежит каноническому треду этой вакансии, ДО удаления — id
    сообщения не должен позволять стереть чужую вакансию. NotFound — не найдена/чужая.
    """
    from core.domains.pipeline.hr_threads import delete_message, get_message, get_primary_thread
    from core.kernel.errors import NotFound

    try:
        thread = await get_primary_thread(vacancy_id, account_id=account_id)
        message = await get_message(message_id, account_id=account_id)
    except RuntimeError as exc:
        raise StorageUnavailable(NO_STORE) from exc
    if thread is None or message is None or message.thread_id != thread.id:
        raise NotFound("Сообщение не найдено")

    try:
        await delete_message(message_id, account_id=account_id)
    except RuntimeError as exc:
        raise StorageUnavailable(NO_STORE) from exc
    return await load_conversation(vacancy_id, account_id=account_id)


async def import_correspondence(
    vacancy_id: str,
    text: str,
    *,
    attachment_ids: Sequence[int] = (),
    attachment_routes: Mapping[int, AttachmentRoute] | None = None,
    account_id: int,
) -> ImportResult:
    """Разобрать вставленный дамп переписки (LLM-сплиттер) → реплики hr_in/hr_out пачкой.

    attachment_ids (Э4-1, плана «носитель текста») — скрины переписки: дожидаемся
    распознавания и подмешиваем `analysis.turns`/`.text` к вручную набранному тексту ДО
    сплиттера — вся отлаженная логика (дедуп, author_uncertain, разбор дат) не переписывается.
    Скриншот-источник вешается связкой на первую созданную реплику пачки (якорь импорта).

    attachment_routes (Э4-3) — ярлык-переключатель ветки с чипа композера, побеждает угадку
    классификатора по `analysis.kind` (см. `attachments_service.resolve_attachment_route`).
    """
    from core.domains.pipeline.hr_import import split_correspondence
    from core.domains.pipeline.hr_threads import add_messages, get_or_create_thread, update_thread

    before = await load_conversation(vacancy_id, account_id=account_id)
    existing = [
        (m.kind, m.body)
        for m in before.messages
        if m.kind in ("hr_in", "hr_out") and (m.body or "").strip()
    ]

    dump_text, unrecognized = await _build_import_text(
        text, attachment_ids, attachment_routes, account_id=account_id
    )
    if not dump_text:
        logger.info("conversations: импорт vacancy_id=%s — нет текста для разбора", vacancy_id)
        return ImportResult(added=0, conversation=before, unrecognized_attachment_ids=unrecognized)

    try:
        split = await split_correspondence(dump_text, existing, account_id=account_id)
    except Exception as exc:
        logger.warning("conversations: LLM-разбор дампа не удался (%s): %s", vacancy_id, exc)
        raise Unprocessable("Не удалось разобрать переписку") from exc

    pairs = split.pairs
    if not pairs:
        logger.info("conversations: импорт vacancy_id=%s — новых реплик нет", vacancy_id)
        return ImportResult(added=0, conversation=before, unrecognized_attachment_ids=unrecognized)

    used_attachment_ids = [i for i in attachment_ids if i not in unrecognized]
    try:
        thread = await get_or_create_thread(
            vacancy_id,
            company=await _company(vacancy_id, account_id=account_id),
            account_id=account_id,
        )
        assert thread.id is not None
        saved = await add_messages(
            [
                HrMessage(
                    thread_id=thread.id,
                    kind=r.kind,
                    body=r.body,
                    sent_at=r.sent_at,
                    author_uncertain=r.author_uncertain,
                )
                for r in pairs
            ],
            account_id=account_id,
        )
        anchor_id = saved[0].id if saved else None
        if used_attachment_ids and anchor_id is not None:
            from core.domains.assistant.attachments.service import link_to_hr_message

            await link_to_hr_message(anchor_id, used_attachment_ids, account_id=account_id)
        if split.hr_contact_name and not (thread.contact_name or "").strip():
            await update_thread(
                thread.id, contact_name=split.hr_contact_name, account_id=account_id
            )
    except (RuntimeError, ValueError) as exc:
        logger.warning("conversations: импорт не записан (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc

    logger.info("conversations: импорт дампа vacancy_id=%s реплик=%d", vacancy_id, len(pairs))
    return ImportResult(
        added=len(pairs),
        added_kinds=[r.kind for r in pairs],
        unrecognized_attachment_ids=unrecognized,
        conversation=await load_conversation(vacancy_id, account_id=account_id),
    )


async def _build_import_text(
    text: str,
    attachment_ids: Sequence[int],
    attachment_routes: Mapping[int, AttachmentRoute] | None = None,
    *,
    account_id: int,
) -> tuple[str, list[int]]:
    """Глеим вручную набранный текст с распознанным текстом скринов переписки (Э4-1).

    Возвращает готовый текст для `split_correspondence` и id вложений, чья ветка (Э4-3,
    `resolve_attachment_route` — kind классификатора либо ручное переопределение с чипа)
    разрешилась не в `correspondence` — для них дампа нет.
    """
    manual = (text or "").strip()
    if not attachment_ids:
        return manual, []

    from core.domains.assistant.attachments import service as attachments_service

    routes = attachment_routes or {}
    metas = await attachments_service.wait_ready(attachment_ids, account_id=account_id)
    parts = [manual] if manual else []
    unrecognized: list[int] = []
    for meta in metas:
        route = attachments_service.resolve_attachment_route(meta.analysis, routes.get(meta.id))
        dump = attachments_service.correspondence_dump(meta.analysis, route)
        if dump:
            parts.append(dump)
        else:
            unrecognized.append(meta.id)
    return "\n\n".join(parts), unrecognized


async def on_incoming_hr_message(vacancy_id: str, trigger: str, *, account_id: int) -> None:
    """Фоновый хвост входящего HR-сообщения: скоринг аутрич-вакансии, пересчёт по фактам,
    извлечение события, предложение статуса воронки, резолв висящего разбора.

    Один фоновый вызов вместо пяти в роутере: порядок и best-effort-семантика те же (каждая
    функция `*_safe` глотает свои ошибки), но кросс-доменный веер живёт в `app`, а не в транспорте.
    """
    from core.domains.opportunities.recalibrate import rescore_from_hr_facts_safe
    from core.domains.pipeline.event_extract import extract_event_safe
    from core.domains.pipeline.funnel_suggest import suggest_funnel_from_dialog_safe
    from core.domains.pipeline.outreach import maybe_score_outreach_vacancy_safe
    from core.domains.preparation.interview.debrief_resolution import (
        resolve_pending_debrief_signal_safe,
    )

    await maybe_score_outreach_vacancy_safe(vacancy_id, account_id=account_id)
    await rescore_from_hr_facts_safe(vacancy_id, trigger=trigger, account_id=account_id)
    await extract_event_safe(vacancy_id, account_id=account_id)
    await suggest_funnel_from_dialog_safe(vacancy_id, account_id=account_id)
    await resolve_pending_debrief_signal_safe(vacancy_id, trigger=trigger, account_id=account_id)


async def attach_vacancy_text_and_rescore(vacancy_id: str, text: str, *, account_id: int):
    """Прикрепить вручную вставленный текст вакансии (сайт без автопарсинга) и пересчитать скор."""
    from core.domains.pipeline.outreach import attach_vacancy_text
    from core.kernel.errors import NotFound

    try:
        return await attach_vacancy_text(vacancy_id, text, account_id=account_id)
    except ValueError as exc:
        raise NotFound("Вакансия не найдена") from exc
    except RuntimeError as exc:
        logger.warning("conversations: текст вакансии не сохранён (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc


async def update_vacancy_identity_and_rescore(
    vacancy_id: str, *, company: str, title: str, account_id: int
):
    """Карандаш в шапке «Чатов»: поправить компанию/должность и пересчитать скор, если уже
    есть чем (executive-recruiter кейс — см. `pipeline.outreach.update_vacancy_identity`)."""
    from core.domains.pipeline.outreach import update_vacancy_identity
    from core.kernel.errors import NotFound

    try:
        return await update_vacancy_identity(
            vacancy_id, company=company, title=title, account_id=account_id
        )
    except ValueError as exc:
        raise NotFound("Вакансия не найдена") from exc
    except RuntimeError as exc:
        logger.warning("conversations: компания/должность не сохранены (нет PG?): %s", exc)
        raise StorageUnavailable(NO_STORE) from exc


async def update_conversation(
    thread_id: int,
    *,
    status=None,
    contact_name=None,
    channel=None,
    company=None,
    pinned: bool | None = None,
    hr_link: str | None = None,
    account_id: int,
) -> HrThread:
    """Правка разговора (статус / контакт / канал / компания / закреп) + best-effort ссылка на HR.

    При переводе в `archived` — дешёвый LLM по переписке решает, увести вакансию в «Отказ»
    (явный отказ HR) или «Пропущено» (иначе). Без ключа/сбоя → пропуск.
    """
    from core.domains.pipeline.hr_threads import update_thread
    from core.kernel.errors import NotFound

    try:
        updated = await update_thread(
            thread_id,
            status=status,
            contact_name=contact_name,
            channel=channel,
            company=company,
            pinned=pinned,
            account_id=account_id,
        )
    except RuntimeError as exc:
        raise StorageUnavailable(NO_STORE) from exc
    if updated is None:
        raise NotFound("Разговор не найден")

    if hr_link is not None:
        from core.domains.opportunities.enrichment import merge_enrichment
        from core.domains.pipeline.hr_identity import normalize_hr_link

        try:
            await merge_enrichment(
                updated.vacancy_id, hr_link=normalize_hr_link(hr_link), account_id=account_id
            )
        except Exception as exc:  # noqa: BLE001 — enrichment best-effort
            logger.warning("conversations: hr_link не сохранён (%s): %s", updated.vacancy_id, exc)

    if status == "archived":
        await _apply_archive_disposition(updated, account_id=account_id)
    return updated


async def _apply_archive_disposition(thread: HrThread, *, account_id: int) -> None:
    """После архива диалога: LLM → Отказ или Пропущено (+ инвалидация внимания через jobs)."""
    from core.domains.opportunities.jobs import add_stage, get_job_by_vacancy_id
    from core.domains.opportunities.skipped import save_skipped
    from core.domains.pipeline.archive_disposition import classify_archive_disposition
    from core.domains.pipeline.hr_threads import list_messages
    from core.kernel.schemas.funnel import FunnelStatus

    try:
        job = await get_job_by_vacancy_id(thread.vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("archive disposition: job недоступен (%s): %s", thread.vacancy_id, exc)
        return
    if job is None or job.id is None:
        return
    # Уже терминал — не перетираем оффер/отказ/пропуск повторным архивом.
    if job.skipped or (job.status or "").strip() in (
        FunnelStatus.REJECTED.value,
        FunnelStatus.OFFER.value,
        FunnelStatus.ARCHIVE.value,
    ):
        return

    try:
        messages = (
            await list_messages(thread.id, account_id=account_id) if thread.id is not None else []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("archive disposition: messages недоступны: %s", exc)
        messages = []

    result = await classify_archive_disposition(
        company=job.company or thread.company or "",
        title=job.title or "",
        messages=messages,
        vacancy_id=thread.vacancy_id,
        account_id=account_id,
    )
    try:
        if result.disposition == "rejected":
            await add_stage(
                job.id, FunnelStatus.REJECTED.value, source="chat_archive", account_id=account_id
            )
            logger.info(
                "archive disposition %s → Отказ (%s)",
                thread.vacancy_id,
                result.reasoning or "—",
            )
        else:
            await save_skipped(
                thread.vacancy_id,
                "Диалог закрыт",
                url=job.url,
                title=job.title,
                company=job.company,
                overall_score=job.overall_score,
                recommendation=job.recommendation,
                account_id=account_id,
            )
            logger.info(
                "archive disposition %s → Пропущено (%s)",
                thread.vacancy_id,
                result.reasoning or "—",
            )
    except Exception as exc:  # noqa: BLE001 — архив диалога уже записан, воронка best-effort
        logger.warning("archive disposition: воронка не обновлена (%s): %s", thread.vacancy_id, exc)


# --------------------------------------------------------------------------- внутреннее


async def _hr_link(vacancy_id: str, *, account_id: int) -> str:
    from core.domains.opportunities.enrichment import load_enrichment

    try:
        enr = await load_enrichment(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — enrichment best-effort
        logger.debug("conversations: hr_link недоступен (%s): %s", vacancy_id, exc)
        return ""
    return (enr.hr_link or "") if enr else ""


async def _company(vacancy_id: str, *, account_id: int) -> str:
    """Компания для денормализации в тред (заголовок «Компания · ID»). Нет PG → пусто."""
    from core.domains.opportunities.jobs import get_job_by_vacancy_id

    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG/вакансии → без компании
        logger.debug("conversations: компания недоступна (%s): %s", vacancy_id, exc)
        return ""
    return (job.company or "") if job else ""


async def _sanitize_suggestion(thread: HrThread, *, account_id: int) -> HrThread:
    """Устаревшее предложение статуса (уже не впереди воронки) не показываем."""
    from core.domains.opportunities.jobs import get_job_by_vacancy_id
    from core.domains.pipeline.funnel_suggest import should_offer_funnel_suggestion

    if not thread.suggested_funnel_status:
        return thread
    try:
        job = await get_job_by_vacancy_id(thread.vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без фильтра предложения
        logger.debug("conversations: статус вакансии недоступен: %s", exc)
        return thread
    status = job.status if job is not None else None
    if status is None or should_offer_funnel_suggestion(
        status, thread.suggested_funnel_status, vacancy_id=thread.vacancy_id
    ):
        return thread
    return thread.model_copy(update={"suggested_funnel_status": None, "suggested_stage_type": None})


def _aware_dt(at: datetime | None) -> datetime | None:
    if at is None:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _attention_key(thread: HrThread) -> datetime:
    """Ключ сортировки attention-списков: всегда datetime (None → минимум)."""
    return _aware_dt(thread.last_hr_at or thread.updated_at) or _SORT_EPOCH


def _silence_days(at: datetime | None, *, now: datetime | None = None) -> int:
    ref = _aware_dt(at)
    if ref is None:
        return 0
    return ((now or datetime.now(UTC)) - ref).days


def _reply_ready(thread: HrThread, *, now: datetime) -> bool:
    """HR написал, и с письма уже прошёл кулдаун — иначе это дубль живого чата, не очередь дня."""
    if thread.last_hr_kind != "hr_in":
        return False
    at = _aware_dt(thread.last_hr_at)
    if at is None:
        return False
    return (now - at) >= timedelta(hours=ATTENTION_REPLY_COOLDOWN_HOURS)


def _has_future_stage(thread: HrThread, *, now: datetime) -> bool:
    """Созвон уже стоит — пинговать HR «напомнить о себе» незачем (как бейдж в ChatsSidebar)."""
    at = _aware_dt(thread.next_stage_at)
    return at is not None and at > now


def _funnel_value(job: Job | None) -> str:
    from core.kernel.schemas.funnel import resolve_funnel_status

    if job is None:
        return ""
    return resolve_funnel_status(job.status) or (job.status or "").strip()


async def _attention_scope(*, account_id: int) -> tuple[list[HrThread], set[str]]:
    """Живые треды для «Ответить»/«Напомнить» и vacancy_id, которые «Сегодня» не трогает.

    `hide` — архив Чатов + пропуск + отказ: ими не спамим ни этапы, ни «свежие сильные».
    `job.skipped` из `get_jobs_by_vacancy_ids` всегда False (колонки нет) —
    смотрим skipped_vacancies.
    """
    from core.domains.opportunities.jobs import get_jobs_by_vacancy_ids
    from core.domains.opportunities.skipped import get_skipped_ids
    from core.domains.pipeline.hr_threads import list_archived_vacancy_ids, list_recent_threads
    from core.kernel.schemas.funnel import FunnelStatus

    hide: set[str] = set()
    try:
        hide |= await list_archived_vacancy_ids(account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без архивного фильтра
        logger.debug("attention: архив тредов недоступен (нет PG?): %s", exc)

    try:
        threads = list(await list_recent_threads(account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → пусто, не 500
        logger.debug("attention: треды недоступны (нет PG?): %s", exc)
        return [], hide

    vids = [t.vacancy_id for t in threads if t.vacancy_id]
    try:
        hide |= await get_skipped_ids(vids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без skipped оставляем треды, кроме уже скрытых
        logger.debug("attention: skipped недоступны: %s", exc)

    try:
        jobs = await get_jobs_by_vacancy_ids(vids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без jobs фильтруем только архив/пропуск
        logger.debug("attention: jobs недоступны: %s", exc)
        return [t for t in threads if t.vacancy_id not in hide], hide

    chat_dead = {FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value, FunnelStatus.OFFER.value}
    calendar_dead = {FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value}
    alive: list[HrThread] = []
    for t in threads:
        vid = t.vacancy_id
        if not vid or vid in hide or t.status == "archived":
            if vid:
                hide.add(vid)
            continue
        status = _funnel_value(jobs.get(vid))
        if status in calendar_dead:
            hide.add(vid)
            continue
        if status in chat_dead:
            continue
        alive.append(t)
    return alive, hide


def _reply_bucket(threads: list[HrThread], *, now: datetime | None = None) -> list[HrThread]:
    moment = now or datetime.now(UTC)
    return sorted(
        (t for t in threads if _reply_ready(t, now=moment)),
        key=_attention_key,
        reverse=True,
    )[:ATTENTION_LIMIT]


def _remind_bucket(threads: list[HrThread], *, now: datetime | None = None) -> list[HrThread]:
    moment = now or datetime.now(UTC)
    return sorted(
        (
            t
            for t in threads
            if t.last_hr_kind == "hr_out"
            and _silence_days(t.last_hr_at, now=moment) >= ATTENTION_REMINDER_DAYS
            and not _has_future_stage(t, now=moment)
        ),
        key=_attention_key,
    )[:ATTENTION_LIMIT]


async def _upcoming_bucket(*, account_id: int, hide: set[str]) -> list[UpcomingStage]:
    from core.domains.opportunities.jobs import get_jobs_by_vacancy_ids
    from core.domains.opportunities.skipped import get_skipped_ids
    from core.domains.preparation.interview_stages import load_upcoming_stages
    from core.kernel.schemas.funnel import FunnelStatus

    calendar_dead = {FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value}
    out: list[UpcomingStage] = []
    try:
        stages = await load_upcoming_stages(
            days=ATTENTION_STRONG_WINDOW_DAYS, account_id=account_id
        )
        vids = [s.vacancy_id for s in stages if s.vacancy_id]
        quiet = set(hide)
        try:
            quiet |= await get_skipped_ids(vids, account_id=account_id)
        except Exception as exc:  # noqa: BLE001 — без skipped оставляем hide как есть
            logger.debug("attention: skipped для этапов недоступны: %s", exc)
        try:
            jobs = await get_jobs_by_vacancy_ids(vids, account_id=account_id)
        except Exception as exc:  # noqa: BLE001 — этапы без компании, фильтр hide всё ещё работает
            logger.debug("attention: jobs для этапов недоступны: %s", exc)
            jobs = {}
        for s in stages:
            vid = s.vacancy_id
            if not vid or vid in quiet:
                continue
            job = jobs.get(vid)
            if _funnel_value(job) in calendar_dead:
                continue
            out.append(
                UpcomingStage(
                    vacancy_id=vid,
                    company=(job.company or "") if job else "",
                    stage_type=s.stage_type,
                    scheduled_at=s.scheduled_at,
                    format=s.format,
                )
            )
            if len(out) >= ATTENTION_LIMIT:
                break
    except Exception as exc:  # noqa: BLE001 — нет PG → пусто
        logger.debug("attention: этапы недоступны (нет PG?): %s", exc)
    return out


async def _strong_unapplied_bucket(*, account_id: int, hide: set[str]) -> list[Job]:
    from core.domains.opportunities.jobs import list_strong_unapplied

    try:
        jobs = await list_strong_unapplied(
            min_score=ATTENTION_STRONG_SCORE,
            days=ATTENTION_STRONG_WINDOW_DAYS,
            limit=min(50, ATTENTION_LIMIT + len(hide)),
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → пусто
        logger.debug("attention: сильные вакансии недоступны (нет PG?): %s", exc)
        return []
    return [j for j in jobs if j.vacancy_id and j.vacancy_id not in hide][:ATTENTION_LIMIT]


__all__ = [
    "AttentionView",
    "ConversationView",
    "ImportResult",
    "OutreachResult",
    "UpcomingStage",
    "add_conversation_message",
    "attach_vacancy_text_and_rescore",
    "create_outreach",
    "delete_conversation_message",
    "import_correspondence",
    "load_attention",
    "load_conversation",
    "on_incoming_hr_message",
    "suggest_attach",
    "update_conversation",
]
