"""Полный текстовый контекст вакансии+подготовки для продолжения диалога во внешнем LLM.

Мотивация владельца: он и так готовится в внешнем Claude/Gemini поверх собранного системой
контекста — раньше вручную копипастил текст вакансии. Здесь —
одна кнопка «Скопировать контекст» (вкладка «Технички»), которая склеивает то, что система уже
знает: вакансию (+ оффер, если есть), HR-переписку, расшифровки прошлых этапов, уже проработанные
вопросы текущего этапа — в один markdown-текст, вставляемый первым сообщением в новый диалог.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domains.preparation.models import STAGE_LABELS
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

# Последние N этапов разбора всегда попадают в экспорт целиком; более старые опускаются первыми,
# если суммарный текст расшифровок выходит за разумный предел вставки в веб-чат (тот же принцип,
# что `truncate_vacancy_text`/MAX_VACANCY_TEXT_CHARS в core.qa.context, но применённый к разбору
# в целом, а не к одному полю).
_KEEP_LAST_STAGES_FULL = 4
_MAX_DEBRIEF_TOTAL_CHARS = 40_000

# Реплик HR-переписки в экспорт — щедрее, чем в чате (assistant._hr_thread_feed, лимит 30):
# там лимит ради длины промпта живого чата, здесь разовая вставка в сторонний диалог.
_HR_FEED_LIMIT = 200

_EXPORT_HEADER = (
    "Контекст вакансии и подготовки к собеседованию. Помоги кандидату подготовиться, "
    "продолжай в том же духе."
)
_EXPORT_HEADER_SCREENING = (
    "Контекст вакансии и подготовки к HR-скринингу. Помоги кандидату подготовиться "
    "к разговору с рекрутером: мотивация, опыт, ожидания по деньгам, вопросы к компании."
)


def _debrief_body(record: Any) -> str:
    analysis = record.analysis if isinstance(record.analysis, dict) else {}
    turns = analysis.get("transcript_turns")
    if isinstance(turns, list) and turns:
        lines = []
        for turn in turns:
            if not isinstance(turn, dict) or not turn.get("text"):
                continue
            speaker = "Интервьюер" if turn.get("speaker") == "interviewer" else "Кандидат"
            lines.append(f"{speaker}: {turn['text']}")
        if lines:
            return "\n".join(lines)
    return record.transcript.strip() or "(текст расшифровки недоступен)"


def _debrief_label(record: Any) -> str:
    stage_label = STAGE_LABELS.get(record.stage, record.stage)
    when = record.created_at.strftime("%d.%m.%Y") if record.created_at else "дата неизвестна"
    return f"### Этап: {stage_label} ({when})"


def _render_debrief_blocks(records: list[Any]) -> list[str]:
    """`records` — свежие первыми (как отдаёт `load_debrief_history`); рендер — в хронологии."""
    chronological = list(reversed(records))
    blocks = [(_debrief_label(r), _debrief_body(r)) for r in chronological]
    total = sum(len(body) for _, body in blocks)
    if total <= _MAX_DEBRIEF_TOTAL_CHARS or len(blocks) <= _KEEP_LAST_STAGES_FULL:
        return [f"{label}\n{body}" for label, body in blocks]

    older, kept = blocks[:-_KEEP_LAST_STAGES_FULL], blocks[-_KEEP_LAST_STAGES_FULL:]
    out = [f"[…опущено {len(older)} более ранних этапов разбора ради длины текста]"]
    out.extend(f"{label}\n{body}" for label, body in kept)
    return out


async def _debriefs_block(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> str:
    from core.domains.preparation.debrief import load_debrief_history

    try:
        records = await load_debrief_history(vacancy_id, limit=200, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG → экспорт без расшифровок, не падаем
        logger.debug("export-context: разборы недоступны: %s", exc)
        return ""
    if not records:
        return ""
    body = "\n\n".join(_render_debrief_blocks(records))
    return f"--- Расшифровки прошлых этапов (хронологически) ---\n\n{body}"


async def _prep_topics_block(
    vacancy_id: str, stage: str | None, *, account_id: int, db: Executor | None = None
) -> str:
    """Список уже сгенерированных вопросов этапа (без ответов) — пометка «уже проработано»."""
    if not stage:
        return ""
    from core.domains.preparation.prep import load_prep_history

    try:
        sessions = await load_prep_history(vacancy_id, limit=50, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG → экспорт без этого блока, не падаем
        logger.debug("export-context: prep-сессии недоступны: %s", exc)
        return ""
    match = next((s for s in sessions if s.stage == stage), None)
    if match is None:
        return ""
    texts = [q.get("text") for q in match.questions if isinstance(q, dict) and q.get("text")]
    if not texts:
        return ""
    lines = [
        f"--- Уже проработанные темы этапа «{STAGE_LABELS.get(stage, stage)}» "
        "(не повторять теми же формулировками) ---"
    ]
    lines.extend(f"- {t}" for t in texts)
    return "\n".join(lines)


async def _screening_pack_block(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> str:
    """Рассказ, вопросы HR и вопросы кандидата — то, чего нет в prep_sessions технички."""
    del db
    from core.domains.preparation.screening.context import load_self_pres_context

    try:
        text = await load_self_pres_context(
            vacancy_id,
            account_id=account_id,
            include_hr_questions=True,
            max_hr_questions=40,
            include_ask_questions=True,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → экспорт без пакета скрининга
        logger.debug("export-context: пакет скрининга недоступен: %s", exc)
        return ""
    if not text:
        return ""
    return f"--- Пакет подготовки к скринингу ---\n\n{text}"


async def build_full_export(
    vacancy_id: str,
    *,
    stage: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> str:
    """Полный текст экспорта под `vacancy_id`. `stage` опционален — без него блок «уже
    проработанных вопросов» не включается. `ValueError` — вакансии нет в `jobs`."""
    from core.domains.pipeline.hr_threads import format_hr_feed
    from core.domains.preparation.interview.records import load_record
    from core.domains.preparation.interview_stages import load_bundle
    from core.domains.preparation.vacancy_context import build_vacancy_context_block

    record = await load_record(vacancy_id, account_id=account_id, db=db)
    if record is None:
        raise ValueError(f"вакансия {vacancy_id} не найдена")

    bundle = None
    try:
        bundle = await load_bundle(vacancy_id, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — нет PG/enrichment → экспорт без него
        logger.debug("export-context: enrichment недоступен: %s", exc)

    offers: list[Any] = []
    try:
        from core.domains.offers.models import OfferRecord
        from core.domains.offers.store import load_active_offers

        raw_offers = await load_active_offers(max_age_days=180, account_id=account_id, db=db)
        offers = [OfferRecord.model_validate(o.model_dump()) for o in raw_offers]
    except Exception as exc:  # noqa: BLE001 — нет PG/офферов → экспорт без рычага-факта
        logger.debug("export-context: активные офферы недоступны: %s", exc)

    vacancy_block = build_vacancy_context_block(record, bundle, offers)

    try:
        hr_feed = await format_hr_feed(
            vacancy_id, limit=_HR_FEED_LIMIT, account_id=account_id, db=db
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → экспорт без переписки
        logger.debug("export-context: HR-лента недоступна: %s", exc)
        hr_feed = ""
    hr_block = (
        f"--- Переписка с HR (реальные сообщения, старые сверху) ---\n\n{hr_feed}"
        if hr_feed
        else ""
    )

    debriefs_block = await _debriefs_block(vacancy_id, account_id=account_id, db=db)
    prep_block = await _prep_topics_block(vacancy_id, stage, account_id=account_id, db=db)
    screening_block = (
        await _screening_pack_block(vacancy_id, account_id=account_id, db=db)
        if stage == "screening"
        else ""
    )

    header = _EXPORT_HEADER_SCREENING if stage == "screening" else _EXPORT_HEADER
    parts = [header, "", vacancy_block]
    for block in (hr_block, screening_block, debriefs_block, prep_block):
        if block:
            parts.extend(["", block])
    return "\n".join(parts)


__all__ = ["build_full_export"]
