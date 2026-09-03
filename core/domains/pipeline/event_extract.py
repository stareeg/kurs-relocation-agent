"""Извлечение договорённостей из входящих HR-реплик: время события + формат следующего этапа
(+ RD-20, один LLM-вызов на оба сигнала).

Дешёвый LLM (haiku, тир `extract`) читает последнюю реплику HR по вакансии и решает:
1. Есть ли конкретная договорённость о времени (созвон/собес/дедлайн) — RD-15.
2. Назвал ли HR формат следующего этапа (даже без даты: «будет лайвкодинг») — RD-20. Раньше это
   умел только парсер бота (`bot_app/services/hr_message_parser.py`) и только на форвардах в
   Telegram; веб-путь (`api/routers/conversations.py`) его не видел. Не переиспользуем тяжёлый
   парсер бота целиком (он заодно детектит компанию/intent/зарплату — не нужно здесь и не дешевле),
   а расширяем уже существующий лёгкий вызов RD-15 общей схемой — один LLM-вызов, не два.

Cost-гард: LLM дёргается только если regex-предфильтр нашёл в тексте признак даты/времени ИЛИ
формата этапа — «спасибо, ждём» не должно стоить денег (тот же подход, что постпроцесс-фильтры
скорера, SM-3).

Хранение — `interview_stages` (цепочка этапов, канон `stage_type`). Матчинг апсерта: ближайший
открытый этап (без даты) ТОГО ЖЕ формата, если формат распознан; иначе любой открытый этап без даты;
иначе новый этап. Уже датированный открытый этап не трогаем — не рискуем затереть реальный,
подтверждённый этап неверной LLM-датой/форматом из другой реплики. `source_message_id` —
ссылка на реплику-источник для бейджа «из переписки» в UI (проверяемость авто-данных).

Опорная дата для относительных дней («в понедельник») — `sent_at` реплики HR, не wall-clock
импорта: дамп часто вставляют уже после созвона.
"""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import get_args

from pydantic import BaseModel, Field

from core.domains.preparation.interview.timing import is_past_datetime, stage_status_from_datetime
from core.domains.preparation.interview_stages import InterviewStage, load_stages, save_stage
from core.domains.preparation.models import STAGE_TYPE_LABELS, InterviewStageType
from core.kernel import ports
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

_MSK = timezone(timedelta(hours=3))
_STAGE_TYPES = frozenset(get_args(InterviewStageType))
_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

# Cost-гард: LLM дёргается только на репликах, где в принципе может быть время/дата/формат этапа.
_PREFILTER = re.compile(
    r"\d{1,2}[:.]\d{2}|\d{1,2}\s*(час|ч\.)|"
    r"понедельник|вторник|сред[ауы]|четверг|пятниц|суббот|воскресень|"
    r"завтра|послезавтра|созвон|встреч|собес|интервью|дедлайн|перенес|"
    r"этап|секци|формат|лайвкод|дизайн|теори|алгоритм|задач",
    re.IGNORECASE,
)

_STAGE_TYPES_HINT = ", ".join(f"{k} ({v})" for k, v in STAGE_TYPE_LABELS.items())

# Признак переноса — уже, чем весь _PREFILTER: пропускаем повторный LLM-вызов, если у вакансии
# уже есть открытый этап с датой в будущем, ЕСЛИ реплика явно не про перенос/отмену этого этапа.
_RESCHEDULE_HINT = re.compile(
    r"перенес|перенос|перенест|друг(ой|ое|ую) (день|врем|дат)|не смогу|не получится|"
    r"сдвин|отмен",
    re.IGNORECASE,
)

_SYSTEM = """\
Ты читаешь свежий фрагмент переписки о вакансии (несколько последних реплик HR и кандидата, для \
контекста — самая свежая реплика HR помечена [HR, последнее]). В ПОСЛЕДНЕЙ реплике HR могут быть \
два независимых сигнала — извлеки оба, если есть:

1. Договорённость о конкретном времени: созвон, собеседование, дедлайн, встреча.
2. Формат СЛЕДУЮЩЕГО этапа собеса, если HR его назвал — даже без даты ("следующим будет лайвкодинг").

Более ранние реплики в фрагменте — ТОЛЬКО контекст: HR иногда называет формат/роль интервьюера в \
одном сообщении («направляю слоты для интервью с руководителем отдела»), а следующим лишь \
подтверждает дату без повтора деталей («договорились, интервью такого-то числа») — в этом случае \
формат/роль сигнала 2 бери из более ранней реплики, а время сигнала 1 — из последней (свежее \
решение важнее устаревшего предложения). Если более ранняя реплика описывает ДРУГУЮ, уже прошедшую \
встречу — не путай её с той, что обсуждается в последней реплике.

Опорная дата реплики (не момент импорта дампа в систему): {anchor} (Москва, UTC+3).
Дамп часто вставляют УЖЕ ПОСЛЕ созвона — дата договорённости вполне может быть в прошлом \
относительно «сейчас на сервере». Относительные дни («в понедельник», «завтра») считай ОТ \
опорной даты реплики, не от текущего момента.

scheduled_at — время (сигнал 1):
- Если время не названо явно (например «на неделе», «скоро», список слотов на выбор без итогового
  решения) — оставь пустым.
- Если названо — ISO 8601 с таймзоной +03:00 (переведи «четверг в 15:00» в конкретную дату
  относительно опорной даты). Не выдумывай дату, если её не назвали явно.
- «В понедельник/вторник/…» при опорной дате: если этот день недели ЕЩЁ не наступил относительно
  опоры (включая сам день опоры, если совпал) — бери ближайший такой день вперёд от опоры;
  если из контекста ясно, что слот уже прошёл (прошедшее время: «созвонились», «был созвон»,
  «вчера», опорная дата позже названного дня на этой неделе) — ставь прошедшую дату, НЕ прыгай
  на следующую неделю.
- Если в реплике назван час/минуты (формат "13:00", "в 13", "13.00") — ОБЯЗАТЕЛЬНО перенеси их в
  ISO как есть, не обнуляй. Время 00:00 в ответе допустимо ТОЛЬКО если реплика буквально называет
  полночь — во всех остальных случаях 00:00 означает, что ты потерял названное время, это ошибка.
  Пример: "созвон в понедельник 13:00" при опоре среда 2026-07-08 → "2026-07-13T13:00:00+03:00"
  (НЕ "2026-07-13T00:00:00+03:00", НЕ вторник 14-го).

stage_type — формат этапа (сигнал 2), одно из: {stage_types}.
- Заполняй ТОЛЬКО если HR явно назвал или однозначно описал формат ("погоняем алгоритмы" →
  live_coding, "поговорим про архитектуру" → system_design, "встреча с руководителем" → manager).
- Не назван или неясен — оставь пустым. Не гадай.

format — "online" (zoom/meet/telegram-звонок) / "offline" (в офисе) / "unknown".

note — 3-8 слов сути своими словами HR по фактам реплики ("2 задачи на алгоритмы, 60 минут, python,
без IDE" или "созвон с HR"). Пусто, если не о чем написать.

Если в реплике нет ни времени, ни формата этапа — верни все поля пустыми/дефолтными.
"""


class _ExtractedEvent(BaseModel):
    scheduled_at: str = ""
    stage_type: str = ""
    format: str = "unknown"
    note: str = Field(default="", max_length=200)


# Сколько недавних hr_in/hr_out реплик даём LLM для контекста вокруг последней hr_in — сигнал
# часто разбит на два сообщения подряд (формат/роль в одном, дата — в следующем, без повтора
# деталей). Инцидент «МТС, Топ менеджмент» (2026-08-12): единственная реплика без контекста не
# несла формата «интервью с руководителем Центра РНД», названного двумя сообщениями раньше — этап
# уходил в дефолт hr_screening вместо manager.
_CONTEXT_WINDOW = 6


def recent_hr_context(messages: list, upto_id: int | None) -> str:
    """Хвост hr_in/hr_out реплик до и включая `upto_id` (последняя hr_in), не длиннее окна.

    llm_user/llm_assistant (болтовня с ассистентом, не с HR) исключены — они не несут сигнала
    про этапы и только разбавляют контекст.
    """
    hr_only = [m for m in messages if m.kind in ("hr_in", "hr_out") and (m.body or "").strip()]
    if upto_id is None:
        idx = len(hr_only) - 1
    else:
        idx = next((i for i, m in enumerate(hr_only) if m.id == upto_id), len(hr_only) - 1)
    window = hr_only[max(0, idx - _CONTEXT_WINDOW + 1) : idx + 1]
    lines = []
    for i, m in enumerate(window):
        who = "HR" if m.kind == "hr_in" else "Кандидат"
        tag = ", последнее" if i == len(window) - 1 and m.kind == "hr_in" else ""
        lines.append(f"[{who}{tag}] {m.body.strip()}")
    return "\n".join(lines)


def _parse_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    with contextlib.suppress(ValueError):
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=_MSK)
    return None


def anchor_label(dt: datetime | None = None) -> str:
    """Подпись опорной даты для промпта: ISO-день + русский день недели (без %A/locale)."""
    local = (dt or datetime.now(tz=_MSK)).astimezone(_MSK)
    return f"{local.strftime('%Y-%m-%d')} ({_WEEKDAYS_RU[local.weekday()]})"


async def _call_llm(text: str, *, anchor: datetime | None = None) -> _ExtractedEvent:
    system = _SYSTEM.format(anchor=anchor_label(anchor), stage_types=_STAGE_TYPES_HINT)
    result = await ports.llm().structured(
        "event_extract",
        system=system,
        user=text[:2000],
        schema=_ExtractedEvent,
        temperature=0.0,
    )
    return result


async def _upsert_stage(
    vacancy_id: str,
    *,
    scheduled_at: datetime | None,
    stage_type: str,
    fmt: str,
    note: str,
    source_message_id: int | None,
    account_id: int,
    db: Executor,
) -> InterviewStage:
    """Ближайший открытый этап без даты того же формата (если формат распознан) — дозаполняем;
    иначе любой открытый этап без даты; иначе новый этап."""
    stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    open_no_date = [s for s in stages if s.status == "scheduled" and s.scheduled_at is None]

    target = None
    if stage_type:
        target = next((s for s in open_no_date if s.stage_type == stage_type), None)
    if target is None:
        target = open_no_date[0] if open_no_date else None
    if target is None:
        # Новый этап, ничего открытого без даты не нашлось. Пустой stage_type здесь значит: LLM
        # не распознала формат даже с расширенным контекстом (recent_hr_context). Дефолт
        # "hr_screening" оправдан только для ПЕРВОГО этапа вакансии — если скрининг уже был
        # (в цепочке уже что-то есть), это почти наверняка следующий этап другого типа, и
        # подписать его «HR-скрининг» вводит в заблуждение сильнее, чем менее точный, но хотя бы
        # не откатывающий воронку назад дефолт "manager" (инцидент «МТС, Топ менеджмент»,
        # 2026-08-12 — HR позвала на интервью с руководителем отдела вторым сообщением, LLM не
        # опознала формат в подтверждении даты, этап ушёл в hr_screening и слился с пройденным
        # скринингом).
        default_type = stage_type or ("hr_screening" if not stages else "manager")
        target = InterviewStage(vacancy_id=vacancy_id, stage_type=default_type)

    update: dict = {"notes": note or target.notes}
    if scheduled_at is not None:
        update["scheduled_at"] = scheduled_at
        update["status"] = stage_status_from_datetime(scheduled_at, "scheduled")
    if stage_type:
        update["stage_type"] = stage_type
    if fmt:
        update["format"] = fmt
    if source_message_id is not None:
        update["source_message_id"] = source_message_id

    saved = await save_stage(target.model_copy(update=update), account_id=account_id, db=db)

    # RD: назначенный звонок — детерминированный факт, что скрининг стартовал. Без LLM: если
    # только что подтверждена дата и вакансия ещё в «Отклик»/«Просмотр» — двигаем воронку сама.
    # Переход дальше («Техничка») намеренно НЕ автоматический — им занимается funnel_suggest.py
    # (LLM-предложение + подтверждение владельцем), запускается следом в том же фоновом триггере.
    if scheduled_at is not None:
        from core.domains.opportunities.jobs import add_stage, get_job_by_vacancy_id
        from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status

        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
        current = resolve_funnel_status(job.status) if job and job.status else None
        if (
            job is not None
            and job.id is not None
            and current
            in (
                FunnelStatus.APPLIED,
                FunnelStatus.VIEWED,
            )
        ):
            await add_stage(
                job.id,
                FunnelStatus.SCREENING.value,
                source="event_extract",
                account_id=account_id,
                db=db,
            )

    return saved


async def extract_event(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> InterviewStage | None:
    """Разобрать последнюю hr_in реплику вакансии: время + формат следующего этапа → этап цепочки."""
    if not vacancy_id:
        return None
    db = db or get_pool()

    from core.domains.pipeline.hr_threads import get_primary_thread, list_messages

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None:
        logger.debug("event_extract: skip vacancy_id=%s reason=no_thread", vacancy_id)
        return None
    messages = await list_messages(thread.id, account_id=account_id, db=db)
    # FR3-74: неуверенная атрибуция не кормит извлечение события (симметрично funnel_suggest.py).
    last_hr_in = next(
        (
            m
            for m in reversed(messages)
            if m.kind == "hr_in" and not m.author_uncertain and (m.body or "").strip()
        ),
        None,
    )
    if last_hr_in is None:
        logger.debug("event_extract: skip vacancy_id=%s reason=no_hr_in", vacancy_id)
        return None

    text = last_hr_in.body.strip()
    if not _PREFILTER.search(text):
        logger.debug("event_extract: skip vacancy_id=%s reason=prefilter_rejected", vacancy_id)
        return None

    # RD: не дёргаем LLM повторно, пока у вакансии уже есть открытый этап с датой в будущем —
    # если только реплика явно не про перенос/отмену (тогда это может быть новая дата).
    open_stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    has_future_open = any(
        s.status == "scheduled"
        and s.scheduled_at is not None
        and not is_past_datetime(s.scheduled_at)
        for s in open_stages
    )
    if has_future_open and not _RESCHEDULE_HINT.search(text):
        logger.debug(
            "event_extract: skip vacancy_id=%s reason=future_stage_already_scheduled", vacancy_id
        )
        return None

    # Опора = sent_at реплики (из дампа Telegram), иначе «сейчас»: иначе «понедельник» при
    # импорте после созвона прыгает на следующую неделю от wall-clock. Окно контекста — вокруг
    # последней hr_in (не только она сама): формат/роль этапа мог быть назван парой сообщений
    # раньше и не повторён в реплике, подтверждающей дату.
    context_text = recent_hr_context(messages, last_hr_in.id) or text
    result = await _call_llm(context_text, anchor=last_hr_in.sent_at)
    scheduled_at = _parse_dt(result.scheduled_at)
    stage_type = result.stage_type.strip() if result.stage_type.strip() in _STAGE_TYPES else ""
    fmt = result.format.strip() if result.format.strip() in ("online", "offline") else ""
    note = result.note.strip()

    if scheduled_at is None and not stage_type and not note:
        logger.debug("event_extract: skip vacancy_id=%s reason=llm_empty", vacancy_id)
        return None

    stage = await _upsert_stage(
        vacancy_id,
        scheduled_at=scheduled_at,
        stage_type=stage_type,
        fmt=fmt,
        note=note,
        source_message_id=last_hr_in.id,
        account_id=account_id,
        db=db,
    )
    logger.info(
        "event_extract: vacancy_id=%s этап id=%s stage_type=%s scheduled_at=%s note=%s",
        vacancy_id,
        stage.id,
        stage_type or "-",
        scheduled_at.isoformat() if scheduled_at else "-",
        note,
    )
    return stage


async def extract_event_safe(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> None:
    """Best-effort обёртка для фонового триггера: исключения не валят запись сообщения."""
    try:
        await extract_event(vacancy_id, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.warning("event_extract: vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


__all__ = ["anchor_label", "extract_event", "extract_event_safe", "recent_hr_context"]
