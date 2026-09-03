"""FR2-86: авто-предложение сдвига воронки из HR-диалога.

После импорта дампа / нового `hr_in` extract-тир через `resolve_stage_type_llm` определяет тип
этапа → `STAGE_TO_FUNNEL_STATUS` → если статус впереди текущего `jobs.status`, пишем предложение
в `hr_threads`. UI показывает чип «Перевести в "Техничка"?»; применение — один клик владельца
(память `feedback_llm_advice_not_user_decision`: LLM предлагает, не применяет сама).

Cost-гард: LLM только при regex-предфильтре на признаки этапа/собеса; «спасибо, ждём» не тратим.
"""

from __future__ import annotations

import logging
import re

from core.domains.preparation.models import STAGE_TO_FUNNEL_STATUS, InterviewStageType
from core.kernel.schemas.funnel import FunnelStatus, funnel_status_rank, resolve_funnel_status
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

# Признаки, что в реплике вообще может быть сигнал про этап (не тратим extract на «ок, жду»).
_PREFILTER = re.compile(
    r"собес|интервью|скрининг|screening|технич|лайвкод|live\s*coding|system\s*design|"
    r"архитектур|теори|менедж|руковод|финал|этап|встреч|созвон|алгоритм|leetcode|"
    r"кейс|business\s*case|onsite|онсайт|soft\s*skill|культур",
    re.IGNORECASE,
)

# Слабый дефолт stage_type_llm при неясности — не предлагаем «Скрининг» без явного намёка.
_SCREENING_HINT = re.compile(
    r"скрининг|screening|знакомств|первичн|созвон с\s*hr|hr[- ]?(call|screen)",
    re.IGNORECASE,
)

# Типы, которые однозначно двигают воронку вперёд (не hr_screening-дефолт).
_ADVANCE_STAGE_TYPES: frozenset[str] = frozenset(
    {
        "live_coding",
        "system_design",
        "theory",
        "business_case",
        "soft_skills",
        "manager",
        "final",
    }
)


def proposed_funnel_for_stage(
    stage_type: InterviewStageType | str,
    *,
    text: str = "",
) -> str | None:
    """Канонический статус воронки для stage_type, или None если предлагать не стоит.

    `hr_screening` → «Скрининг» только при явном намёке в тексте (иначе stage_type_llm часто
    отдаёт его как безопасный дефолт на любой неясный кусок).
    """
    raw = (stage_type or "").strip()
    if raw not in STAGE_TO_FUNNEL_STATUS:
        return None
    if raw == "hr_screening" and not _SCREENING_HINT.search(text or ""):
        return None
    if raw != "hr_screening" and raw not in _ADVANCE_STAGE_TYPES:
        return None
    return STAGE_TO_FUNNEL_STATUS[raw]


def should_offer_funnel_suggestion(
    current_status: str | None,
    proposed_status: str | None,
    *,
    vacancy_id: str | None = None,
) -> bool:
    """Предлагать только сдвиг вперёд; равный/ниже/пустой — нет.

    §9 плана `local_context_blind_spots_2026_08_12.md`: функцию ни разу не подтвердило реальное
    срабатывание (0 строк `funnel_suggest:` в `copilot_logs` за всю историю аккаунта) — калибровка
    regex-префильтров и `stage_type_llm` не проверена практикой. Лог на каждой развилке (не только
    на `True`) — чтобы при следующем реальном вызове было видно, почему функция промолчала или
    сработала, без гадания по коду/повторного SQL-расследования.
    """
    if not proposed_status or not str(proposed_status).strip():
        event(
            logger,
            "ЗАДАЧА",
            "funnel_suggest: отклонено — proposed пуст (vacancy_id=%s, cur=%s)",
            vacancy_id or "—",
            current_status or "—",
        )
        return False
    prop = resolve_funnel_status(proposed_status) or proposed_status.strip()
    if prop in (FunnelStatus.REJECTED, FunnelStatus.ARCHIVE, FunnelStatus.VIEWED):
        event(
            logger,
            "ЗАДАЧА",
            "funnel_suggest: отклонено — proposed=%s не двигает воронку вперёд "
            "(vacancy_id=%s, cur=%s)",
            prop,
            vacancy_id or "—",
            current_status or "—",
        )
        return False
    cur = resolve_funnel_status(current_status) if current_status else None
    if cur and funnel_status_rank(prop) <= funnel_status_rank(cur):
        event(
            logger,
            "ЗАДАЧА",
            "funnel_suggest: отклонено — rank(%s)=%d не выше rank(%s)=%d (vacancy_id=%s)",
            prop,
            funnel_status_rank(prop),
            cur,
            funnel_status_rank(cur),
            vacancy_id or "—",
        )
        return False
    if not cur:
        allowed = funnel_status_rank(prop) > funnel_status_rank(FunnelStatus.VIEWED)
        event(
            logger,
            "ЗАДАЧА",
            "funnel_suggest: %s — cur пуст, rank(%s)=%d %s rank(viewed)=%d (vacancy_id=%s)",
            "предложено" if allowed else "отклонено",
            prop,
            funnel_status_rank(prop),
            ">" if allowed else "<=",
            funnel_status_rank(FunnelStatus.VIEWED),
            vacancy_id or "—",
        )
        return allowed
    event(
        logger,
        "ЗАДАЧА",
        "funnel_suggest: предложено — %s → %s (rank %d > %d, vacancy_id=%s)",
        cur,
        prop,
        funnel_status_rank(prop),
        funnel_status_rank(cur),
        vacancy_id or "—",
    )
    return True


async def suggest_funnel_from_dialog(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> str | None:
    """Последняя hr_in → предложить статус воронки (или None)."""
    if not vacancy_id:
        return None
    db = db or get_pool()

    from core.domains.opportunities.jobs import get_job_by_vacancy_id
    from core.domains.pipeline.hr_threads import (
        clear_funnel_suggestion,
        get_primary_thread,
        list_messages,
        set_funnel_suggestion,
    )
    from core.domains.pipeline.stage_type_llm import resolve_stage_type_llm

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None:
        return None
    messages = await list_messages(thread.id, account_id=account_id, db=db)
    # FR3-74: неуверенная атрибуция не кормит предложение воронки.
    last_hr_in = next(
        (
            m
            for m in reversed(messages)
            if m.kind == "hr_in" and not m.author_uncertain and (m.body or "").strip()
        ),
        None,
    )
    if last_hr_in is None:
        return None

    text = last_hr_in.body.strip()
    if not _PREFILTER.search(text):
        return None

    # Тот же источник уже обработан — не дёргаем LLM повторно.
    if (
        thread.suggestion_source_message_id is not None
        and last_hr_in.id is not None
        and thread.suggestion_source_message_id == last_hr_in.id
        and thread.suggested_funnel_status
    ):
        return thread.suggested_funnel_status

    # Окно контекста вокруг последней hr_in (не только она сама) — формат/роль этапа мог быть
    # назван парой сообщений раньше и не повторён в реплике, подтверждающей дату (см.
    # event_extract.recent_hr_context — та же причина мисклассификации, тот же приём).
    from core.domains.pipeline.event_extract import recent_hr_context

    context_text = recent_hr_context(messages, last_hr_in.id) or text
    resolved = await resolve_stage_type_llm(context_text, vacancy_id=vacancy_id)
    reason = ""
    if resolved is None:
        from core.domains.pipeline.hr_enrichment import infer_stage_type

        stage_type = infer_stage_type(text, {})
    else:
        stage_type, reason = resolved

    proposed = proposed_funnel_for_stage(stage_type, text=text)
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    current = job.status if job is not None else None

    if not should_offer_funnel_suggestion(current, proposed, vacancy_id=vacancy_id):
        # Новая реплика без сдвига — снимем устаревшее предложение от предыдущей.
        if thread.suggested_funnel_status:
            await clear_funnel_suggestion(thread.id, account_id=account_id, db=db)
        return None

    assert proposed is not None
    await set_funnel_suggestion(
        thread.id,
        funnel_status=proposed,
        stage_type=stage_type,
        source_message_id=last_hr_in.id,
        account_id=account_id,
        db=db,
    )
    event(
        logger,
        "ЗАДАЧА",
        "funnel_suggest: vacancy_id=%s %s → %s (stage_type=%s) — %s",
        vacancy_id,
        current or "—",
        proposed,
        stage_type,
        reason or "—",
        vacancy_id=vacancy_id,
        funnel_status=proposed,
        stage_type=stage_type,
        reasoning=reason,
    )
    return proposed


async def suggest_funnel_from_dialog_safe(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> None:
    """Best-effort обёртка для фонового триггера: исключения не валят запись сообщения."""
    try:
        await suggest_funnel_from_dialog(vacancy_id, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.warning("funnel_suggest: vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


async def apply_funnel_suggestion(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> str | None:
    """Применить сохранённое предложение → jobs.status; очистить чип.

    Возвращает применённый статус или None, если предложения нет / оно устарело.
    """
    if not vacancy_id:
        return None
    db = db or get_pool()

    from core.domains.opportunities.jobs import (
        SOURCE_HH_APPLY_STUB,
        Job,
        add_stage,
        get_job_by_vacancy_id,
        save_job,
    )
    from core.domains.pipeline.hr_threads import clear_funnel_suggestion, get_primary_thread

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None or not thread.suggested_funnel_status:
        return None

    raw = thread.suggested_funnel_status
    proposed = resolve_funnel_status(raw) or raw
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    current = job.status if job is not None else None
    if not should_offer_funnel_suggestion(current, proposed, vacancy_id=vacancy_id):
        await clear_funnel_suggestion(thread.id, account_id=account_id, db=db)
        return None

    if job is None:
        job = await save_job(
            Job(
                vacancy_id=vacancy_id,
                vacancy_text="",
                url=f"https://hh.ru/vacancy/{vacancy_id}",
                status=proposed,
                source=SOURCE_HH_APPLY_STUB,
            ),
            account_id=account_id,
            db=db,
        )
    assert job.id is not None
    await add_stage(job.id, proposed, source="funnel_suggest", account_id=account_id, db=db)
    await clear_funnel_suggestion(thread.id, account_id=account_id, db=db)
    logger.info("funnel_suggest: применено vacancy_id=%s → %s", vacancy_id, proposed)
    return proposed


async def dismiss_funnel_suggestion(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Снять чип без смены воронки. True — предложение было и очищено."""
    db = db or get_pool()
    from core.domains.pipeline.hr_threads import clear_funnel_suggestion, get_primary_thread

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None or not thread.suggested_funnel_status:
        return False
    await clear_funnel_suggestion(thread.id, account_id=account_id, db=db)
    return True


__all__ = [
    "apply_funnel_suggestion",
    "dismiss_funnel_suggestion",
    "proposed_funnel_for_stage",
    "should_offer_funnel_suggestion",
    "suggest_funnel_from_dialog",
    "suggest_funnel_from_dialog_safe",
]
