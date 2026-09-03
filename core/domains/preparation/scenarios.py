"""Сценарии домена preparation, снятые с роутеров.

Здесь всё, что целиком внутри контекста подготовки: подготовка к этапу, темы, оверлей sobes,
бриф, история разборов, цепочка этапов. Кросс-доменное (чат подготовки → `assistant`,
разбор собеса → `opportunities.enrichment`) живёт в `core/app/scenarios/`.

Общий вход у большинства сценариев — `VacancyRef`: карточка вакансии, как её видит фронт
(текст + заголовок + компания + вилка + оценка). Из неё собирается `VacancyRecord` для
prep-движка — тем же `record_from_request_fallback`, что и раньше в роутере.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from core.domains.preparation.asker import record_from_request_fallback
from core.domains.preparation.interview.company_profiles import (
    CompanyProfile,
    match_company_profile,
)
from core.domains.preparation.interview.prep import (
    SOBES_OVERLAY_MAX_CHARS,
    build_sobes_context,
    checklist_for_stage,
    expand_prep_topic,
    framework_for_stage,
    generate_prep_questions,
    generate_prep_questions_events,
    generate_vacancy_prep_topics,
)
from core.domains.preparation.interview.prep_pack import generate_prep_pack
from core.domains.preparation.interview_stages import InterviewStage
from core.domains.preparation.models import (
    DebriefAnalysis,
    PrepQuestion,
    ScoreResult,
    VacancyRecord,
)
from core.domains.preparation.prep_pack import get_prep_pack
from core.kernel.errors import (
    DomainError,
    InternalError,
    InvalidInput,
    NotFound,
    StorageUnavailable,
)
from core.kernel.hashing import input_digest

logger = logging.getLogger(__name__)

#: Минимальная длина текста вакансии, при которой есть что готовить (иначе 400).
MIN_VACANCY_TEXT = 50

_NO_PG = "Postgres недоступен"
_NO_CONTEXT = "Контекст вакансии недоступен."


class VacancyRef(BaseModel):
    """Карточка вакансии, как её присылает фронт/расширение (может быть неполной)."""

    vacancy_id: str
    vacancy_text: str = ""
    title: str = ""
    company: str = ""
    salary_text: str = ""
    score: ScoreResult | None = None


class PrepView(BaseModel):
    """Подготовка под (вакансия, этап): вопросы + статический чеклист + каркас ответа."""

    vacancy_id: str
    stage: str
    questions: list[PrepQuestion] = []
    checklist: list[str] = []
    framework: list[str] = []
    generated_at: datetime | None = None
    source: Literal["empty", "saved", "generated"] = "empty"
    company_profile: CompanyProfile | None = None


class SobesOverlay(BaseModel):
    """Компактный контекст для оверлея sobes.tech под выбранный формат этапа."""

    available: bool = False
    markdown: str = ""
    stage: str = ""
    char_limit: int = SOBES_OVERLAY_MAX_CHARS

    @property
    def char_count(self) -> int:
        return len(self.markdown)


def build_record(ref: VacancyRef, *, fallback_text: str = _NO_CONTEXT) -> VacancyRecord:
    """`VacancyRef` → `VacancyRecord` для prep-движка; пустой текст заменяем заглушкой."""
    return record_from_request_fallback(
        ref.vacancy_id,
        vacancy_text=(ref.vacancy_text or "").strip() or fallback_text,
        title=ref.title,
        company=ref.company,
        salary_text=ref.salary_text,
        score=ref.score,
    )


# --------------------------------------------------------------------------- подготовка к этапу


async def load_prep(
    vacancy_id: str, stage: str, company: str | None = None, *, account_id: int
) -> PrepView:
    """Последняя сохранённая подготовка под (вакансия, этап). Нет PG/сессии → статический чеклист.

    `company` (из карточки воронки) подбирает профиль РФ-бигтеха и подгоняет состав подготовки.
    """
    profile = await match_company_profile(company, account_id=account_id)
    empty = _prep_view(vacancy_id, stage, profile)
    session = await _saved_session(vacancy_id, stage, account_id=account_id)
    if session is None:
        return empty
    return _prep_view(
        vacancy_id,
        stage,
        profile,
        questions=_questions_from_jsonb(session.questions),
        generated_at=session.generated_at,
        source="saved",
    )


async def generate_prep(
    ref: VacancyRef, stage: str, focus_topics: list[str] | None = None, *, account_id: int
) -> PrepView:
    """Сгенерировать подготовку под этап (LLM) и best-effort сохранить сессию в PG."""
    _require_vacancy_text(ref)
    profile = await match_company_profile(
        ref.company, ref.vacancy_text or "", account_id=account_id
    )
    logger.info(
        "prep: vacancy_id=%s stage=%s profile=%s",
        ref.vacancy_id,
        stage,
        profile.key if profile else "-",
    )
    questions = await generate_prep_questions(
        build_record(ref), stage, profile, focus_topics=focus_topics, account_id=account_id
    )
    return _prep_view(
        ref.vacancy_id,
        stage,
        profile,
        questions=questions,
        generated_at=await _save_session(ref.vacancy_id, stage, questions, account_id=account_id),
        source="generated",
    )


async def generate_prep_events(
    ref: VacancyRef, stage: str, focus_topics: list[str] | None = None, *, account_id: int
) -> AsyncIterator[dict[str, Any]]:
    """Поток сборки подготовки: вопросы приезжают частями, в конце `done` с сохранённой
    сессией. Ошибку не поднимаем наружу — SSE-соединение уже открыто, клиент ждёт кадр: последним
    уходит `{"type": "error"}` (транспорт A-14 кодирует в `event: error`)."""
    try:
        _require_vacancy_text(ref)
        profile = await match_company_profile(
            ref.company, ref.vacancy_text or "", account_id=account_id
        )
        logger.info(
            "prep: vacancy_id=%s stage=%s profile=%s (stream)",
            ref.vacancy_id,
            stage,
            profile.key if profile else "-",
        )
        record = build_record(ref)
        answers: list[dict[str, Any]] = []
        ask_them: list[dict[str, Any]] = []
        async for event in generate_prep_questions_events(
            record, stage, profile, focus_topics=focus_topics, account_id=account_id
        ):
            etype = event.get("type")
            if etype in ("status", "part_error"):
                yield event
            elif etype == "answers":
                answers = event.get("questions") or []
                yield {"type": "questions", "questions": [*answers, *ask_them]}
            elif etype == "ask_them":
                ask_them = event.get("questions") or []
                yield {"type": "questions", "questions": [*answers, *ask_them]}
            elif etype == "done":
                questions = [PrepQuestion.model_validate(q) for q in (event.get("questions") or [])]
                generated_at = await _save_session(
                    ref.vacancy_id, stage, questions, account_id=account_id
                )
                view = _prep_view(
                    ref.vacancy_id,
                    stage,
                    profile,
                    questions=questions,
                    generated_at=generated_at,
                    source="generated",
                )
                yield {"type": "done", "prep": view}
    except DomainError as exc:
        yield {"type": "error", "detail": exc.message}
    except Exception as exc:  # noqa: BLE001 — SSE-соединение уже открыто, клиент ждёт кадр
        logger.error("prep: stream error: %s", exc)
        yield {"type": "error", "detail": "не удалось собрать подготовку"}


async def saved_prep_questions(
    vacancy_id: str, stage: str, *, account_id: int
) -> list[PrepQuestion]:
    """Заготовленные вопросы этапа из последней сессии — фоновый контекст для чата и оверлея."""
    session = await _saved_session(vacancy_id, stage, limit=20, account_id=account_id)
    return _questions_from_jsonb(session.questions if session else [])


async def regenerate_prep_pack(ref: VacancyRef, stage: str, *, account_id: int) -> tuple[str, str]:
    """Собрать свежий бриф отдельным вызовом LLM. Ничего не сохраняет — это кандидат для ревью.

    L-19: вход (вакансия+этап) не изменился с последней сборки → отдаём сохранённый текст,
    LLM не зовём. Возвращает `(text, input_hash)` — хэш прокидывается в `save_prep_pack`, чтобы
    следующий вызов снова мог сравнить вход.
    """
    _require_vacancy_text(ref)
    digest = _prep_pack_input_hash(ref, stage)
    saved = await get_prep_pack(ref.vacancy_id, stage, account_id=account_id)
    if saved.content.strip() and saved.input_hash == digest:
        return saved.content, digest
    profile = await match_company_profile(
        ref.company, ref.vacancy_text or "", account_id=account_id
    )
    text = await generate_prep_pack(build_record(ref), stage, profile, account_id=account_id)
    return text, digest


def _prep_pack_input_hash(ref: VacancyRef, stage: str) -> str:
    score_part = str(ref.score.overall_score) if ref.score else ""
    return input_digest(
        ref.vacancy_id, stage, ref.title, ref.company, ref.salary_text, ref.vacancy_text, score_part
    )


async def build_sobes_overlay(
    ref: VacancyRef, stage: str, *, account_id: int, force: bool = False
) -> SobesOverlay:
    """Контекст для оверлея sobes.tech: достаточно текста вакансии + этапа, prep не обязателен.

    Чат в промпт не кладём (там часто огромные внешние переписки); темы берём из `prep_topics`,
    если они уже есть.
    """
    prep_questions = await saved_prep_questions(ref.vacancy_id, stage, account_id=account_id)
    topics = [t.topic for t in await load_topics(ref.vacancy_id, stage, account_id=account_id)]

    if (
        len((ref.vacancy_text or "").strip()) < MIN_VACANCY_TEXT
        and not prep_questions
        and not force
    ):
        return SobesOverlay(stage=stage)
    markdown = await build_sobes_context(
        build_record(ref), stage, prep_questions, account_id=account_id, topics=topics or None
    )
    return SobesOverlay(available=True, markdown=markdown, stage=stage)


# --------------------------------------------------------------------------- темы


async def load_topics(vacancy_id: str, stage: str, *, account_id: int) -> list:
    """Готовность по темам под (вакансия, этап). Нет PG/тем → пустой список."""
    try:
        from core.domains.preparation.prep_topics import load_prep_topics

        return list(await load_prep_topics(vacancy_id, stage, account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → без тем, вкладка не падает
        logger.debug("prep topics: чтение недоступно: %s", exc)
        return []


async def generate_topics(
    ref: VacancyRef, stage: str, *, account_id: int, force: bool = False
) -> list:
    """Сгенерировать темы по вакансии (LLM). Без `force` не перетирает уже сохранённый набор."""
    from core.domains.preparation.prep_topics import replace_prep_topics

    existing = await load_topics(ref.vacancy_id, stage, account_id=account_id)
    if existing and not force:
        return existing
    try:
        topics = await generate_vacancy_prep_topics(build_record(ref), stage)
        return list(await replace_prep_topics(ref.vacancy_id, stage, topics, account_id=account_id))
    except DomainError:  # LlmError и прочие доменные — наверх как есть
        raise
    except Exception as exc:  # noqa: BLE001 — упало сохранение (нет PG)
        logger.error("prep topics: генерация/сохранение: %s", exc)
        raise StorageUnavailable(str(exc)) from exc


async def review_topics(
    vacancy_id: str,
    stage: str,
    *,
    account_id: int,
    topics: list[str],
    question_text: str = "",
    question_topic_hint: str | None = None,
    answer_excerpt: str | None = None,
) -> list:
    """Засчитать раскрытие ответа: явные темы или LLM-маппинг вопроса на каталог."""
    from core.domains.preparation.prep_topics import review_prep_topics

    try:
        chosen = list(topics)
        if not chosen and question_text.strip():
            catalog = [t.topic for t in await load_topics(vacancy_id, stage, account_id=account_id)]
            if catalog:
                from core.domains.preparation.interview.prep import map_question_to_prep_topics

                chosen = await map_question_to_prep_topics(
                    question_text,
                    catalog,
                    hint_topic=question_topic_hint,
                    answer_excerpt=answer_excerpt,
                )
        return list(await review_prep_topics(vacancy_id, stage, chosen, account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — без PG засчитывать некуда
        logger.error("prep topics review: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def expand_topic(ref: VacancyRef, stage: str, topic: str, *, account_id: int) -> str:
    """П.5c: короткая шпаргалка по теме (LLM, basic tier).

    Stateless-раскрытие темы из разбора реального собеса — по клику на тему в блоке «Темы».
    Кэшируется через общий llm_result_cache; ничего не пишет в БД.
    """
    del account_id  # нет записи в БД, аккаунт нужен только для трассировки
    try:
        return await expand_prep_topic(topic, build_record(ref), stage)
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001 — LLM/сетевые — наверх как DomainError
        logger.error("prep topic expand: %s", exc)
        raise InternalError(str(exc)) from exc


# --------------------------------------------------------------------------- разборы


async def debrief_history(vacancy_id: str, limit: int = 50, *, account_id: int) -> list:
    """История разборов по вакансии (свежие первыми). Нет PG → пустой список."""
    try:
        from core.domains.preparation.debrief import load_debrief_history

        return list(await load_debrief_history(vacancy_id, limit=limit, account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая история
        logger.debug("debrief: история из Postgres недоступна: %s", exc)
        return []


async def debrief_stage_index(*, account_id: int) -> list[tuple[str, str]]:
    """Пары (vacancy_id, stage) с готовым разбором. Нет PG → пустой список."""
    try:
        from core.domains.preparation.debrief import load_debrief_stage_index

        return list(await load_debrief_stage_index(account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → отметок в рельсе просто не будет
        logger.debug("debrief: индекс этапов из Postgres недоступен: %s", exc)
        return []


async def patch_debrief_transcript(
    vacancy_id: str, debrief_id: int, transcript: str, *, account_id: int
):
    """Поправить текст транскрипта в ленте — без повторного LLM-разбора.

    Сегментация на реплики (`transcript_turns`) сбрасывается репозиторием: старая относится
    к старому тексту.
    """
    from core.domains.preparation.debrief import update_transcript

    rec = await update_transcript(debrief_id, transcript, account_id=account_id)
    if rec is None or rec.vacancy_id != vacancy_id:
        raise NotFound("Разбор не найден")
    if _analysis_or_none(rec.analysis) is None:
        raise InternalError("Разбор повреждён")
    return rec


def analysis_of(record) -> DebriefAnalysis:
    """Разбор из jsonb-строки истории; битый разбор уже отфильтрован вызывающим."""
    return _analysis_or_none(record.analysis) or DebriefAnalysis()


def parse_analysis(raw: Any) -> DebriefAnalysis | None:
    """Публичная обёртка над разбором jsonb: None — строку показывать нельзя."""
    return _analysis_or_none(raw)


# --------------------------------------------------------------------------- цепочка этапов


async def list_stages(vacancy_id: str, *, account_id: int) -> list[InterviewStage]:
    """Цепочка этапов вакансии по порядку. Нет PG → пустой список, степпер не валится."""
    try:
        from core.domains.preparation.interview_stages import load_stages

        return list(await load_stages(vacancy_id, account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая цепочка
        logger.debug("interview-stages: список недоступен (Postgres?): %s", exc)
        return []


async def create_stage(
    vacancy_id: str,
    *,
    stage_type: str,
    scheduled_at: datetime | None = None,
    format: str | None = None,
    notes: str = "",
    account_id: int,
) -> InterviewStage:
    """Добавить этап из канона в конец цепочки (без явной `position` — уезжает в хвост)."""
    from core.domains.preparation.interview_stages import save_stage

    try:
        return await save_stage(
            InterviewStage(
                vacancy_id=vacancy_id,
                stage_type=stage_type,
                scheduled_at=scheduled_at,
                format=format or "unknown",
                notes=notes.strip(),
            ),
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → этап некуда писать
        logger.warning("interview-stages: этап не сохранён (Postgres?): %s", exc)
        raise StorageUnavailable("Postgres недоступен — этап не сохранён") from exc


async def reorder_stages(
    vacancy_id: str, ordered_ids: list[int], *, account_id: int
) -> list[InterviewStage]:
    """Переставить порядок цепочки (перетаскивание в UI)."""
    from core.domains.preparation.interview_stages import reorder_stages as _reorder

    try:
        return list(await _reorder(vacancy_id, ordered_ids, account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → порядок некуда писать
        logger.warning("interview-stages: порядок не сохранён (Postgres?): %s", exc)
        raise StorageUnavailable("Postgres недоступен — порядок не сохранён") from exc


async def patch_stage(
    vacancy_id: str, stage_id: int, patch: dict, *, account_id: int
) -> InterviewStage:
    """Точечная правка этапа (дата/формат/статус/заметка) — PATCH-семантика, None = не менять."""
    from core.domains.preparation.interview_stages import save_stage

    existing = await _require_stage(vacancy_id, stage_id, account_id=account_id)
    try:
        return await save_stage(existing.model_copy(update=patch), account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → правку некуда писать
        logger.warning("interview-stages: правка не сохранена (Postgres?): %s", exc)
        raise StorageUnavailable("Postgres недоступен — этап не изменён") from exc


async def remove_stage(vacancy_id: str, stage_id: int, *, account_id: int) -> None:
    """Убрать этап из цепочки (этого формата у этой компании нет)."""
    from core.domains.preparation.interview_stages import delete_stage

    await _require_stage(vacancy_id, stage_id, account_id=account_id)
    try:
        await delete_stage(stage_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → нечего удалять
        logger.warning("interview-stages: удаление не выполнено (Postgres?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


# --------------------------------------------------------------------------- внутреннее


def _require_vacancy_text(ref: VacancyRef) -> None:
    if len((ref.vacancy_text or "").strip()) < MIN_VACANCY_TEXT:
        raise InvalidInput("vacancy_text не передан или слишком короткий")


def _prep_view(
    vacancy_id: str,
    stage: str,
    profile: CompanyProfile | None,
    *,
    questions: list[PrepQuestion] | None = None,
    generated_at: datetime | None = None,
    source: Literal["empty", "saved", "generated"] = "empty",
) -> PrepView:
    return PrepView(
        vacancy_id=vacancy_id,
        stage=stage,
        questions=questions or [],
        checklist=checklist_for_stage(stage, profile),
        framework=framework_for_stage(stage),
        generated_at=generated_at,
        source=source,
        company_profile=profile,
    )


async def _saved_session(vacancy_id: str, stage: str, *, account_id: int, limit: int = 50):
    """Последняя сохранённая prep-сессия под этап; нет PG/сессии → None."""
    try:
        from core.domains.preparation.prep import load_prep_history

        sessions = await load_prep_history(vacancy_id, limit=limit, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → отдаём статический чеклист
        logger.debug("prep: история из Postgres недоступна: %s", exc)
        return None
    return next((s for s in sessions if s.stage == stage), None)


async def _save_session(
    vacancy_id: str, stage: str, questions: list[PrepQuestion], *, account_id: int
):
    """Накопительный конспект: сохраняем сессию, чтобы не генерить заново (LLM = деньги)."""
    try:
        from core.domains.preparation.prep import PrepSession, save_prep_session

        saved = await save_prep_session(
            PrepSession(
                vacancy_id=vacancy_id,
                stage=stage,
                questions=[q.model_dump() for q in questions],
                status="generated",
            ),
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → подготовка всё равно отдаётся
        logger.debug("prep: сессия не сохранена (Postgres недоступен): %s", exc)
        return None
    return saved.generated_at


def _questions_from_jsonb(rows) -> list[PrepQuestion]:
    """jsonb-словари prep-сессии → типизированные вопросы; битые молча пропускаем."""
    out: list[PrepQuestion] = []
    for raw in rows or []:
        if not isinstance(raw, dict) or not raw.get("text"):
            continue
        try:
            out.append(PrepQuestion(**raw))
        except Exception:  # noqa: BLE001 — битый вопрос пропускаем
            continue
    return out


def _analysis_or_none(raw: Any) -> DebriefAnalysis | None:
    if not raw:
        return DebriefAnalysis()
    try:
        return DebriefAnalysis(**raw)
    except Exception as exc:  # noqa: BLE001 — битый jsonb не должен ронять всю историю
        logger.warning("debrief: разбор не распарсен: %s", exc)
        return None


async def _require_stage(vacancy_id: str, stage_id: int, *, account_id: int) -> InterviewStage:
    existing = next(
        (s for s in await list_stages(vacancy_id, account_id=account_id) if s.id == stage_id),
        None,
    )
    if existing is None:
        raise NotFound("Этап не найден")
    return existing


__all__ = [
    "MIN_VACANCY_TEXT",
    "PrepView",
    "SobesOverlay",
    "VacancyRef",
    "analysis_of",
    "build_record",
    "build_sobes_overlay",
    "create_stage",
    "debrief_history",
    "debrief_stage_index",
    "generate_prep",
    "generate_prep_events",
    "generate_topics",
    "list_stages",
    "load_prep",
    "load_topics",
    "parse_analysis",
    "patch_debrief_transcript",
    "patch_stage",
    "regenerate_prep_pack",
    "remove_stage",
    "reorder_stages",
    "review_topics",
    "saved_prep_questions",
]
