"""Чат подготовки по вакансии.

Кросс-доменный сценарий: ответ и пачки вопросов — `preparation`, лента реплик — `assistant`
(`prep_chat_messages`). Раньше склейка жила в `api/routers/preparation/prep.py`.

Персист реплик обязателен: чат без записи молча потеряет подготовку, поэтому нет Postgres → 503,
а не тихая деградация. Всё остальное (prep-сессии, бриф) — фоновый контекст и деградирует.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from core.domains.assistant.attachments.models import AttachmentMeta, AttachmentRoute
from core.domains.assistant.prep_chat import PrepChatMessage, append_prep_chat
from core.domains.preparation.interview.company_profiles import match_company_profile
from core.domains.preparation.interview.prep import (
    answer_prep_chat,
    format_external_transcript_message,
    parse_external_prep_chat,
)
from core.domains.preparation.models import ChatAnswer, PrepQuestion
from core.domains.preparation.scenarios import VacancyRef, build_record, saved_prep_questions
from core.kernel import ports
from core.kernel.errors import StorageUnavailable, Unprocessable

logger = logging.getLogger(__name__)

_NO_PG = "Postgres недоступен — чат не сохранён"
_NOTHING_TO_PARSE = "Вставьте переписку или прикрепите скриншот"
# Э4-2, §3 плана: скрин, распознанный НЕ как переписка, не годится для parse_external —
# отправляем его как обычное вложение диалога (тот же приём, что Э3 «Технички · Агент»).
_EXTERNAL_MATERIAL_MESSAGE = (
    "Сторонний материал (скрин). Выдели суть и как это относится к вакансии."
)


class PrepChatReply(BaseModel):
    """Ответ чата: сохранённая реплика ассистента + (если просили) новая пачка вопросов."""

    message: PrepChatMessage
    questions: list[PrepQuestion] = []
    topic: str | None = None


async def send_message(
    ref: VacancyRef,
    *,
    stage: str,
    message: str,
    history: list[dict[str, str]],
    account_id: int,
    focus_topics: list[str] | None = None,
    reply_to_message_id: int | None = None,
    attachment_ids: Sequence[int] = (),
) -> PrepChatReply:
    """Сообщение в чат подготовки: LLM отвечает с контекстом вакансии, prep-вопросов и брифа.

    Сохранённые вопросы сессии и бриф идут в промпт фоном — чтобы ассистент не повторял уже
    закрытые темы и понимал «сгенерируй ещё пачку» / «объясни подробнее».

    attachment_ids (Э3-1, план chat_image_attachments) — картинки ТЕКУЩЕЙ реплики (готовые id
    из POST /api/attachments): уходят в модель инлайном (правило истории, §3 плана — прошлые
    вложения текстом, Э3-3) и связываются с репликой владельца при сохранении. Текстовые
    документы (txt/md/pdf/docx, 2026-08-11) — одним блоком в сообщение пользователя
    (`load_llm_context`, симметрично `assistant.service`).
    """
    images, doc_text = await _load_current_attachments(attachment_ids, account_id=account_id)
    user_message = f"{message}\n\n{doc_text}".strip() if doc_text else message
    answer = await answer_prep_chat(
        build_record(ref),
        user_message,
        history,
        stage=stage,
        account_id=account_id,
        profile=await match_company_profile(
            ref.company, ref.vacancy_text or "", account_id=account_id
        ),
        focus_topics=focus_topics,
        prep_questions=await saved_prep_questions(ref.vacancy_id, stage, account_id=account_id),
        pack_content=await _pack_content(ref.vacancy_id, stage, account_id=account_id),
        images=images,
    )
    questions = await _store_questions(
        ref.vacancy_id, stage, answer, account_id=account_id, required=False
    )
    saved = await _store_exchange(
        ref.vacancy_id,
        message,
        answer.text,
        account_id=account_id,
        reply_to_message_id=reply_to_message_id,
        attachment_ids=attachment_ids,
    )
    return PrepChatReply(message=saved, questions=questions, topic=_topic(answer, questions))


async def parse_external(
    ref: VacancyRef,
    *,
    stage: str,
    transcript: str,
    account_id: int,
    attachment_ids: Sequence[int] = (),
    attachment_routes: Mapping[int, AttachmentRoute] | None = None,
) -> PrepChatReply:
    """Разобрать внешнюю переписку → вопросы в prep-сессию + короткая реплика в ленту.

    attachment_ids (Э4-2, плана «носитель текста») — скрины переписки с внешним ИИ: тот же
    приём, что у HR-импорта (Э4-1) — дожидаемся распознавания и подмешиваем `analysis.text`/
    `.turns` к вручную набранному тексту ДО парсера, отлаженная логика `parse_external_prep_chat`
    не переписывается. Картинки, чья ветка (Э4-3, `attachment_routes` — ярлык-переключатель с
    чипа, побеждает угадку по kind) не «переписка», для дампа не годятся — уходят в «вложение
    диалога» (Э3, `send_message`) с канонической просьбой «выдели суть».

    Полный диалог сохраняем в user-реплике под маркером — UI показывает ярлык и «Скопировать».
    В отличие от обычного сообщения, потеря разобранных вопросов недопустима: не записались → 503.
    """
    correspondence_text, correspondence_ids, material_ids = await _split_external_attachments(
        attachment_ids, attachment_routes, account_id=account_id
    )
    manual = (transcript or "").strip()
    dump_text = "\n\n".join(p for p in (manual, correspondence_text) if p)

    if dump_text:
        answer = await parse_external_prep_chat(
            build_record(ref),
            dump_text,
            stage=stage,
            existing_questions=await saved_prep_questions(
                ref.vacancy_id, stage, account_id=account_id
            ),
        )
        questions = await _store_questions(
            ref.vacancy_id, stage, answer, account_id=account_id, required=True
        )
        saved = await _store_exchange(
            ref.vacancy_id,
            format_external_transcript_message(dump_text),
            answer.text,
            account_id=account_id,
            attachment_ids=correspondence_ids,
        )
        return PrepChatReply(message=saved, questions=questions, topic=_topic(answer, questions))

    if material_ids:
        return await send_message(
            ref,
            stage=stage,
            message=_EXTERNAL_MATERIAL_MESSAGE,
            history=[],
            account_id=account_id,
            attachment_ids=material_ids,
        )

    raise Unprocessable(_NOTHING_TO_PARSE)


async def _split_external_attachments(
    attachment_ids: Sequence[int],
    attachment_routes: Mapping[int, AttachmentRoute] | None = None,
    *,
    account_id: int,
) -> tuple[str, list[int], list[int]]:
    """Скрины `parse_external` по ветке (Э4-2/Э4-3, `resolve_attachment_route`): переписка →
    текст в дамп + её id для связки-якоря; всё остальное (материал/не распозналось/владелец
    переопределил ярлыком) → id для вложения диалога."""
    if not attachment_ids:
        return "", [], []

    from core.domains.assistant.attachments import service as attachments_service

    routes = attachment_routes or {}
    metas = await attachments_service.wait_ready(attachment_ids, account_id=account_id)
    parts: list[str] = []
    correspondence_ids: list[int] = []
    material_ids: list[int] = []
    for meta in metas:
        route = attachments_service.resolve_attachment_route(meta.analysis, routes.get(meta.id))
        dump = attachments_service.correspondence_dump(meta.analysis, route)
        if dump:
            parts.append(dump)
            correspondence_ids.append(meta.id)
        else:
            material_ids.append(meta.id)
    return "\n\n".join(parts), correspondence_ids, material_ids


async def delete_message(
    vacancy_id: str, message_id: int, *, account_id: int
) -> list[PrepChatMessage]:
    """Удалить одну реплику ленты (выделение → Удалить во фронте). NotFound — не найдена/чужая."""
    from core.domains.assistant.prep_chat import delete_prep_chat_message
    from core.kernel.errors import NotFound

    try:
        deleted = await delete_prep_chat_message(vacancy_id, message_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → 503, не тихая деградация
        raise StorageUnavailable(_NO_PG) from exc
    if not deleted:
        raise NotFound("Сообщение не найдено")
    return await load_history(vacancy_id, account_id=account_id)


async def clear_chat(vacancy_id: str, *, account_id: int) -> int:
    """Сбросить ленту чата подготовки. Нет PG → нечего чистить, отвечаем нулём."""
    try:
        from core.domains.assistant.prep_chat import clear_prep_chat

        return await clear_prep_chat(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → нечего чистить
        logger.debug("prep chat: очистка недоступна: %s", exc)
        return 0


async def load_history(
    vacancy_id: str, *, account_id: int, limit: int = 100
) -> list[PrepChatMessage]:
    """История чата подготовки (хронологически). Нет PG → пустой список, вкладка не падает."""
    try:
        from core.domains.assistant.prep_chat import load_prep_chat

        return list(await load_prep_chat(vacancy_id, account_id=account_id, limit=limit))
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой чат
        logger.debug("prep chat: история недоступна: %s", exc)
        return []


# --------------------------------------------------------------------------- внутреннее


async def _pack_content(vacancy_id: str, stage: str, *, account_id: int) -> str | None:
    """Собранный бриф этапа — фон, чтобы чат не повторял уже закрытые темы.

    stage="screening" — свой источник: self-pres пакет раздела «Скрининги» (легенда, мосты,
    вопросы обеих сторон), а не общий `prep_pack` Техничек — тот для этого этапа никогда не
    собирается (Технички явно исключают hr_screening из своего пайплайна подготовки, см.
    features/tech/TechPage.tsx::isHrScreening). Без этой ветки агент в чате Скринингов не видел
    вообще ничего из того, что показано на экране, и не мог осмысленно советовать по ответам.
    """
    try:
        if stage == "screening":
            from core.domains.preparation.screening.context import load_self_pres_context

            text = await load_self_pres_context(
                vacancy_id,
                account_id=account_id,
                max_hr_questions=20,
                include_ask_questions=True,
            )
            return text or None

        from core.domains.preparation.prep_pack import get_prep_pack

        return (await get_prep_pack(vacancy_id, stage, account_id=account_id)).content
    except Exception as exc:  # noqa: BLE001 — нет PG → чат без брифа, не валим
        logger.debug("prep chat: бриф недоступен: %s", exc)
        return None


async def _store_questions(
    vacancy_id: str, stage: str, answer: ChatAnswer, *, account_id: int, required: bool
) -> list[PrepQuestion]:
    """Новая пачка — не текст в пузыре, а настоящие карточки в `prep_sessions`.

    В чате (`required=False`) потеря пачки допустима: реплика ассистента всё равно сохранится.
    В разборе внешней переписки (`required=True`) — нет: вопросы и есть результат.
    """
    if answer.kind != "questions" or not answer.questions:
        return []
    try:
        from core.domains.preparation.prep import append_prep_questions

        await append_prep_questions(vacancy_id, stage, answer.questions, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — см. docstring
        logger.error("prep chat: новая пачка вопросов не сохранена (нет PG?): %s", exc)
        if required:
            raise StorageUnavailable("Postgres недоступен") from exc
        return []
    return list(answer.questions)


async def _store_exchange(
    vacancy_id: str,
    user_text: str,
    assistant_text: str,
    *,
    account_id: int,
    reply_to_message_id: int | None = None,
    attachment_ids: Sequence[int] = (),
) -> PrepChatMessage:
    """Обе реплики в ленту. Не записались → 503: терять подготовку владельца нельзя.

    reply_to_message_id несёт только реплика владельца (composer «Ответить») — тот же паттерн,
    что у llm_user в hr_messages. attachment_ids (Э3-1, плана) — связка создаётся здесь же,
    в момент персиста реплики владельца, не раньше.
    """
    try:
        user_message = await append_prep_chat(
            vacancy_id,
            "user",
            user_text,
            account_id=account_id,
            reply_to_message_id=reply_to_message_id,
        )
        if attachment_ids and user_message.id is not None:
            from core.domains.assistant.attachments.service import link_to_prep_chat_message

            await link_to_prep_chat_message(
                user_message.id, list(attachment_ids), account_id=account_id
            )
        return await append_prep_chat(
            vacancy_id, "assistant", assistant_text, account_id=account_id
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → реплика теряется, нельзя
        logger.error("prep chat: сохранение не удалось (нет PG?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def _load_current_attachments(
    attachment_ids: Sequence[int], *, account_id: int
) -> tuple[list[ports.ImageInput], str]:
    """Вложения ТЕКУЩЕЙ реплики для LLM-вызова (правило истории, §3 плана — инлайном уходят
    только картинки текущего сообщения; прошлые — текстом, Э3-3; текстовые документы —
    одним блоком с спотлайтингом, симметрично `assistant.service._load_current_attachments`)."""
    if not attachment_ids:
        return [], ""
    from core.domains.assistant.attachments import service as attachments_service

    return await attachments_service.load_llm_context(attachment_ids, account_id=account_id)


async def load_message_attachments(
    messages: Sequence[PrepChatMessage], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения этих реплик (Э3-1) для проекции ленты в API — нет PG/таблицы → пусто, не 500."""
    message_ids = [m.id for m in messages if m.id is not None]
    if not message_ids:
        return {}
    try:
        from core.domains.assistant.attachments.service import load_for_prep_chat_messages

        return await load_for_prep_chat_messages(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — best-effort, как остальной кросс-доменный контекст
        logger.debug("prep chat: вложения сообщений недоступны: %s", exc)
        return {}


def _topic(answer: ChatAnswer, questions: list[PrepQuestion]) -> str | None:
    return answer.topic if questions else None


__all__ = [
    "PrepChatReply",
    "clear_chat",
    "delete_message",
    "load_history",
    "load_message_attachments",
    "parse_external",
    "send_message",
]
