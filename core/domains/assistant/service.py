"""Прямой стрим чата: SSE-токены идут из домена, без промежуточного оркестратора.

Свободный диалог с LLM на agent-тире; токены уходят в SSE сразу из `stream_answer`.
Историю диалога фронт передаёт в `payload['history']` (контекст треда явный).

Режим «чат по вакансии»: `vacancy` + опц. `tier` → системный промпт как у Q&A, тир reasoning.
Режим «разбор пробелов резюме»: `resume_gap=true` — диалог с персистом в resume_chat_messages.
Режим «черновик ответа HR»: `hr_draft=true` + `vacancy` — без персиста и без follow-ups.
Режим «чат по ситуации на рынке»: `market=true` — диалог с карьерным стратегом, персист в
market_chat_messages; заменяет бывший односторонний блок «Что сделать» (next-steps).
Режим «чат по офферам»: `offers=true` — советник по условиям/торгу, персист в
offers_chat_messages; контекст карточек собирается на каждый запрос.

Подсказки продолжения: после ответа — короткий structured-вызов на той же модели.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from core.config import CoreSettings, get_settings
from core.kernel import ports
from core.platform.observability import event

if TYPE_CHECKING:
    from core.domains.offers.models import OfferRecord
    from core.domains.profile.gap import ResumeGapReport

logger = logging.getLogger(__name__)

CHAT_AGENT = "chat"
# Короче этого — подсказки продолжения не окупают лишний LLM-вызов (короткий ответ типа «да»).
_FOLLOWUP_MIN_ANSWER_LEN = 60


class _FollowUps(BaseModel):
    """2-3 коротких варианта продолжения диалога от лица владельца (п.3)."""

    suggestions: list[str] = Field(default_factory=list)


# Сколько последних реплик диалога подмешивать в контекст (защита от раздувания запроса).
_MAX_HISTORY = 12


def _extract_message(task_input: dict[str, Any]) -> str:
    for key in ("message", "question", "text", "input", "q"):
        val = task_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _history_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Прошлые реплики из payload['history'] ({role, text}) → сообщения порта (role/content)."""
    raw = payload.get("history")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[-_MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        role = "assistant" if item.get("role") == "assistant" else "user"
        out.append({"role": role, "content": text.strip()})
    return out


@lru_cache(maxsize=1)
def _chat_system_template() -> str:
    """Сырой текст файла-промпта чата — кэш по пути, диск не перечитываем на каждый вызов."""
    from core.domains.assistant.llm import CHAT_SYSTEM

    path = Path(CHAT_SYSTEM)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт chat не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


async def _load_prompt(settings: CoreSettings, *, account_id: int) -> str:
    from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    return _chat_system_template().replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )


def _vacancy_payload(task_input: dict[str, Any]) -> dict[str, Any] | None:
    """`vacancy` из payload (дровер веба): текст/оценка/мета конкретной вакансии."""
    vac = task_input.get("vacancy")
    return vac if isinstance(vac, dict) and vac else None


def _is_resume_gap(task_input: dict[str, Any]) -> bool:
    """Флаг `resume_gap` из payload (вкладка «Резюме», кнопка «Разобрать пробелы»)."""
    return bool(task_input.get("resume_gap"))


def _is_hr_draft(task_input: dict[str, Any]) -> bool:
    """Флаг `hr_draft` из payload (композер диалога, кнопка «Черновик» + интент-чип)."""
    return bool(task_input.get("hr_draft"))


def _is_market_chat(task_input: dict[str, Any]) -> bool:
    """Флаг `market` из payload (вкладка «Рынок», чат по ситуации под графиками).

    Заменяет бывший блок «Что сделать» (next-steps) свободным диалогом с карьерным
    стратегом — персист в market_chat_messages, модель `market_chat`.
    """
    return bool(task_input.get("market"))


def _is_offers_chat(task_input: dict[str, Any]) -> bool:
    """Флаг `offers` из payload (вкладка «Офферы», чат под карточками).

    Советник по условиям/торгу — персист в offers_chat_messages, модель `offers_chat`.
    Контекст карточек собирается на каждый запрос.
    """
    return bool(task_input.get("offers"))


def _extract_reply_to_message_id(task_input: dict[str, Any]) -> int | None:
    """`reply_to_message_id` из payload (composer «Ответить») — id реплики-источника цитаты."""
    raw = task_input.get("reply_to_message_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _extract_attachment_ids(task_input: dict[str, Any]) -> list[int]:
    """`attachment_ids` из payload (композер «Чаты · Агент», Э2-5) — картинки текущей реплики."""
    raw = task_input.get("attachment_ids")
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for v in raw:
        if isinstance(v, bool):  # bool это подтип int — отбрасываем
            continue
        if isinstance(v, int) and v > 0 and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def _load_current_attachments(
    attachment_ids: list[int], *, account_id: int
) -> tuple[list[ports.ImageInput], str]:
    """Вложения ТЕКУЩЕЙ реплики (правило истории, §3 плана: инлайном уходят только вложения
    текущего сообщения, прошлые — текстом, см. `_past_attachments_block`) — картинки для
    мультимодального вызова + текст документов (txt/md/pdf/docx, 2026-08-11) одним блоком."""
    if not attachment_ids:
        return [], ""
    from core.domains.assistant.attachments import service as attachments_service

    return await attachments_service.load_llm_context(attachment_ids, account_id=account_id)


async def _past_attachments_block(vacancy_id: str, *, account_id: int) -> str:
    """Картинки из ПРОШЛЫХ реплик этого разговора — только текстом (`analysis.title`/`.text`),
    иначе каждый следующий вопрос переотправлял бы весь альбом в модель (плана).

    Best-effort: нет PG/треда/готового разбора → пустая строка, чат не падает.
    """
    if not vacancy_id:
        return ""
    try:
        from core.domains.assistant.attachments.service import load_for_hr_messages
        from core.domains.pipeline.hr_threads import get_primary_thread, list_messages
        from core.kernel.text import wrap_untrusted

        thread = await get_primary_thread(vacancy_id, account_id=account_id)
        if thread is None or thread.id is None:
            return ""
        messages = await list_messages(thread.id, account_id=account_id)
        message_ids = [m.id for m in messages if m.id is not None]
        by_message = await load_for_hr_messages(message_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без блока, не валим чат
        logger.debug("chat: вложения истории недоступны: %s", exc)
        return ""
    if not by_message:
        return ""

    lines: list[str] = []
    for metas in by_message.values():
        for meta in metas:
            if meta.analysis_status != "ready" or meta.analysis is None:
                continue
            title = meta.analysis.title.strip() or "Скриншот"
            text = meta.analysis.text.strip()
            line = f"- {title}"
            if text:
                line += f": {wrap_untrusted(text, source='attachment')}"
            lines.append(line)
    if not lines:
        return ""
    return "## Картинки из истории этого диалога (текстом, не сами изображения)\n\n" + "\n".join(
        lines
    )


async def _reply_quote_block(message_id: int, *, account_id: int) -> str:
    """Текст реплики-источника цитатой в промпт — best-effort: нет PG / не найдена → пусто."""
    try:
        from core.domains.pipeline.hr_threads import get_message

        msg = await get_message(message_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — цитата best-effort, не блокирует ответ
        logger.debug("chat: цитата ответа недоступна (id=%s): %s", message_id, exc)
        return ""
    if msg is None or not msg.body.strip():
        return ""
    label = "HR" if msg.kind == "hr_in" else "Ассистент" if msg.kind == "llm_assistant" else "Я"
    snippet = " ".join(msg.body.split())[:600]
    return f'Владелец отвечает на реплику из переписки ({label}): "{snippet}"'


async def _market_reply_quote_block(message_id: int, *, account_id: int) -> str:
    """Аналог `_reply_quote_block` для чата «Рынка» (market_chat_messages, не hr_messages)."""
    try:
        from core.domains.market.market_chat import get_market_chat_message

        msg = await get_market_chat_message(message_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — цитата best-effort, не блокирует ответ
        logger.debug("chat: цитата ответа (рынок) недоступна (id=%s): %s", message_id, exc)
        return ""
    if msg is None or not msg.content.strip():
        return ""
    label = "Ассистент" if msg.role == "assistant" else "Я"
    snippet = " ".join(msg.content.split())[:600]
    return f'Владелец отвечает на реплику из чата ({label}): "{snippet}"'


async def _resume_reply_quote_block(message_id: int, *, account_id: int) -> str:
    """Аналог `_market_reply_quote_block` для чата по резюме (resume_chat_messages)."""
    try:
        from core.domains.assistant.resume_chat import get_resume_chat_message

        msg = await get_resume_chat_message(message_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — цитата best-effort, не блокирует ответ
        logger.debug("chat: цитата ответа (резюме) недоступна (id=%s): %s", message_id, exc)
        return ""
    if msg is None or not msg.content.strip():
        return ""
    label = "Ассистент" if msg.role == "assistant" else "Я"
    snippet = " ".join(msg.content.split())[:600]
    return f'Владелец отвечает на реплику из чата ({label}): "{snippet}"'


async def _offers_reply_quote_block(message_id: int, *, account_id: int) -> str:
    """Аналог `_market_reply_quote_block` для чата «Офферы» (offers_chat_messages)."""
    try:
        from core.domains.offers.offers_chat import get_offers_chat_message

        msg = await get_offers_chat_message(message_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — цитата best-effort, не блокирует ответ
        logger.debug("chat: цитата ответа (офферы) недоступна (id=%s): %s", message_id, exc)
        return ""
    if msg is None or not msg.content.strip():
        return ""
    label = "Ассистент" if msg.role == "assistant" else "Я"
    snippet = " ".join(msg.content.split())[:600]
    return f'Владелец отвечает на реплику из чата ({label}): "{snippet}"'


def _explicit_note_ids(task_input: dict[str, Any]) -> list[int]:
    """Явный выбор контекстов владельцем (UI-селектор под композером чата).

    Список id заметок, которые владелец явно прикрепил к сообщению. Валидируем как int и
    отсекаем дубли/пустоту. None/не-список → пусто (используется auto-top-K по теме).
    """
    raw = task_input.get("note_ids")
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for v in raw:
        if isinstance(v, bool):  # bool это подтип int — отбрасываем
            continue
        if isinstance(v, int) and v > 0 and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def _explicit_notes_block(note_ids: list[int], *, account_id: int) -> str:
    """Текстовый блок явно выбранных заметок для системного промпта. Best-effort: нет PG / нет
    таких id → пустая строка (не падаем, просто без блока)."""
    if not note_ids:
        return ""
    try:
        from core.domains.assistant.notes import build_notes_context_block, get_notes_by_ids

        notes = await get_notes_by_ids(note_ids, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без явных заметок
        logger.debug("chat: явные заметки не загружены (нет PG?): %s", exc)
        return ""
    return build_notes_context_block(notes)


def _safe_score(raw: Any):
    """jsonb-оценка из jobs может разойтись со схемой ScoreResult - парсим терпимо, иначе None.

    Это и был источник падения старого пути `/vacancies/{id}/ask`: FastAPI валидировал score строго
    и ронял весь запрос. Здесь payload свободный, а контекст вакансии полезен и без оценки.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        from core.domains.opportunities.models import ScoreResult

        return ScoreResult.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — без оценки отвечаем по тексту/резюме
        logger.debug("chat: score вакансии не прошёл валидацию ScoreResult: %s", exc)
        return None


async def _vacancy_record_and_bundle(vacancy: dict[str, Any], *, account_id: int):
    """`VacancyRecord` + enrichment/этапы + активный оффер из Postgres (best-effort) - общее для
    vacancy/hr_draft.

    Импорт core.qa/core.repo ленивый - не тянем LLM/PG стек в старт модуля.
    """
    from core.domains.preparation.asker import record_from_request_fallback
    from core.domains.preparation.interview_stages import load_bundle

    record = record_from_request_fallback(
        str(vacancy.get("vacancy_id") or ""),
        vacancy_text=str(vacancy.get("vacancy_text") or ""),
        title=vacancy.get("title"),
        company=vacancy.get("company"),
        salary_text=vacancy.get("salary_text"),
        score=_safe_score(vacancy.get("score")),
    )

    bundle = None
    try:
        if record.vacancy_id:
            pg = await load_bundle(record.vacancy_id, account_id=account_id)
            if pg.enrichment is not None or pg.stages:
                bundle = pg
    except Exception as exc:  # noqa: BLE001 — нет PG/enrichment → чат работает без него
        logger.debug("chat: enrichment вакансии из Postgres недоступен: %s", exc)

    # Активные офферы кандидата - факт-рычаг для чата/HR-черновика по ЛЮБОЙ вакансии, в
    # т.ч. ДРУГОЙ (пример: оффер POSCREDIT виден в контексте чата по финалу Сбера, хотя офферы
    # разные вакансии) - специально не фильтруем по record.vacancy_id. Best-effort, как bundle.
    offers: list[OfferRecord] = []
    try:
        from core.domains.offers.models import OfferRecord
        from core.domains.offers.store import load_active_offers

        raw_offers = await load_active_offers(max_age_days=180, account_id=account_id)
        offers = [OfferRecord.model_validate(o.model_dump()) for o in raw_offers]
    except Exception as exc:  # noqa: BLE001 — нет PG/офферов → чат работает без них
        logger.debug("chat: активные офферы из Postgres недоступны: %s", exc)

    return record, bundle, offers


async def _vacancy_system_parts(
    vacancy: dict[str, Any], message: str, *, account_id: int
) -> tuple[str, str]:
    """L-11: (статичный qa-prefix, dynamic_tail с вакансией/HR/заметками).

    `message` - текущий вопрос кандидата, по нему top-K заметок.
    FR3-54: при наличии кэша пакета скрининга добавляем секцию подготовки.
    """
    from core.domains.assistant.notes import notes_context_block_for_topic
    from core.domains.preparation.prompts import build_qa_system_prompt
    from core.domains.preparation.screening.context import load_self_pres_context
    from core.domains.preparation.vacancy_context import build_vacancy_context_block

    record, bundle, offers = await _vacancy_record_and_bundle(vacancy, account_id=account_id)

    hr_feed = await _hr_thread_feed(record.vacancy_id or "", account_id=account_id)
    hr_section = (
        f"\n\n## Переписка с HR (актуальная, реальные сообщения, самые новые внизу)\n\n{hr_feed}"
        if hr_feed
        else ""
    )

    notes_block = await notes_context_block_for_topic(message, account_id=account_id)
    notes_section = f"\n\n{notes_block}" if notes_block else ""

    prep_section = ""
    try:
        prep = await load_self_pres_context(record.vacancy_id or "", account_id=account_id)
        if prep:
            prep_section = f"\n\n## Подготовка к скринингу (кэш под эту вакансию)\n\n{prep}"
    except Exception as exc:  # noqa: BLE001 — нет PG → чат без пакета
        logger.debug("chat: пакет скрининга недоступен: %s", exc)

    career_section = ""
    try:
        from core.domains.career.facts import load_facts_context_block

        career_block = await load_facts_context_block(account_id=account_id)
        if career_block.strip():
            career_section = f"\n\n## Долгая память кандидата\n\n{career_block}"
    except Exception as exc:  # noqa: BLE001
        logger.debug("chat: career_facts недоступны: %s", exc)

    attachments_block = await _past_attachments_block(
        record.vacancy_id or "", account_id=account_id
    )
    attachments_section = f"\n\n{attachments_block}" if attachments_block else ""

    dynamic = (
        "## Контекст вакансии (для этого диалога)\n\n"
        f"{build_vacancy_context_block(record, bundle, offers)}"
        f"{hr_section}"
        f"{prep_section}"
        f"{career_section}"
        f"{notes_section}"
        f"{attachments_section}"
    )
    return await build_qa_system_prompt(account_id=account_id), dynamic


async def _hr_thread_feed(vacancy_id: str, *, account_id: int) -> str:
    """Реальная HR-лента вакансии (hr_in/hr_out, без llm-болтовни) - старые сверху, до 30 реплик."""
    if not vacancy_id:
        return ""
    try:
        from core.domains.pipeline.hr_threads import format_hr_feed

        return await format_hr_feed(vacancy_id, limit=30, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → черновик без ленты, не падаем
        logger.debug("chat: hr_draft лента переписки недоступна: %s", exc)
        return ""


async def _candidate_salary_line(*, account_id: int) -> str:
    """Зарплатная вилка кандидата аккаунта запроса из резюме («от X до Y ₽») - best-effort,
    пусто если резюме нет."""
    try:
        from core.domains.profile.model import _salary_range_md
        from core.domains.profile.structured_store import read_resume_data_for_account

        data = await read_resume_data_for_account(account_id)
        return _salary_range_md(data.position)
    except Exception as exc:  # noqa: BLE001 — нет резюме/PG → пустая строка, шаблон подставит дефолт
        logger.debug("chat: hr_draft зарплатная вилка недоступна: %s", exc)
        return ""


async def _hr_draft_lang(vacancy: dict[str, Any], *, account_id: int) -> Literal["ru", "en"]:
    """Язык черновика (Э4.5): трек вакансии `second_job` или резюме преимущественно на
    английском → "en", иначе "ru". Без ручного тумблера - у композера HR-треда нет для него места.
    """
    if str(vacancy.get("track") or "").strip() == "second_job":
        return "en"
    try:
        from core.domains.profile.international import detect_resume_language
        from core.domains.profile.structured_store import read_resume_data_for_account

        resume = await read_resume_data_for_account(account_id)
        return detect_resume_language(resume)
    except Exception as exc:  # noqa: BLE001 — нет резюме/PG → безопасный дефолт "ru"
        logger.debug("chat: hr_draft автодетект языка недоступен: %s", exc)
        return "ru"


async def _hr_draft_system_prompt(vacancy: dict[str, Any], intent: str, *, account_id: int) -> str:
    """Системный промпт черновика ответа HR под интент-чип - `core.domains.pipeline.hr_draft`.

    FR3-54: легенда для промпта - кэш пакета скрининга под этой vacancy_id (oral_pitch / мосты к
    вакансии / why / hr Q&A). Нет пакета (скрининг ещё не собирался) → черновик без легенды.
    """
    from core.domains.pipeline.hr_draft import build_hr_draft_system_prompt
    from core.domains.preparation.screening.context import load_self_pres_context
    from core.domains.preparation.vacancy_context import build_vacancy_context_block

    record, bundle, offers = await _vacancy_record_and_bundle(vacancy, account_id=account_id)
    vacancy_block = build_vacancy_context_block(record, bundle, offers)

    hr_feed = await _hr_thread_feed(record.vacancy_id or "", account_id=account_id)
    salary_line = await _candidate_salary_line(account_id=account_id)
    lang = await _hr_draft_lang(vacancy, account_id=account_id)

    legend_text = ""
    try:
        legend_text = await load_self_pres_context(record.vacancy_id or "", account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → без легенды, не падаем
        logger.debug("chat: hr_draft пакет скрининга недоступен: %s", exc)

    return await build_hr_draft_system_prompt(
        account_id=account_id,
        intent=intent,
        title=record.title or str(vacancy.get("title") or ""),
        company=record.company or str(vacancy.get("company") or ""),
        vacancy_block=vacancy_block,
        hr_feed=hr_feed,
        legend=legend_text,
        lang=lang,
        salary_line=salary_line,
    )


@lru_cache(maxsize=1)
def _resume_gap_template() -> str:
    """Сырой текст файла-промпта resume_gap_chat — кэш, диск не перечитываем на каждый вызов."""
    from core.domains.assistant.llm import RESUME_GAP_CHAT_PROMPT as _PROMPT_PATH

    path = Path(_PROMPT_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт resume_gap_chat не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


def _resume_score_block(report: ResumeGapReport | None) -> str:
    """Блок балла резюме + четырёх факторов (Каркас/Покрытие рынка/Формулировки/Релевантность
    роли) + слабых буллетов — те же метрики, что владелец видит в левой панели «Резюме».

    Нет gap-отчёта (PG лежит / резюме пустое) → пустой блок, модель отвечает без него.
    """
    if report is None or report.score is None:
        return ""
    s = report.score
    factors = [
        f"- Каркас (structure): {s.structure}/100",
        f"- Покрытие рынка (market_coverage): {s.market_coverage if s.market_coverage is not None else 'нет данных'}",
        f"- Формулировки (writing): {s.writing}/100",
        f"- Релевантность роли (role_fit): {s.role_fit}/100",
    ]
    lines = [f"## Балл резюме: {s.total}/100", "", "Факторы (те, что в левой панели):", *factors]
    if s.weak_bullets:
        lines.append("")
        lines.append("Слабые буллеты (без цифры/метрики и без глагола действия):")
        for i, w in enumerate(s.weak_bullets[:12], start=1):
            reason = f" — {w.reason}" if (w.reason or "").strip() else ""
            lines.append(f"{i}. [{w.ref}] «{w.text}»{reason}")
    if s.role_fit_notes:
        lines.append("")
        lines.append("Заметки по релевантности роли:")
        for note in s.role_fit_notes[:8]:
            lines.append(f"- {note}")
    if report.missing:
        lines.append("")
        lines.append(
            f"Востребовано рынком, но НЕ упомянуто в резюме (топ-{min(len(report.missing), 10)}):"
        )
        for m in report.missing[:10]:
            lines.append(f"- {m.name} — {m.demand_pct:g}% вакансий требуют")
    return "\n".join(lines)


async def _resume_gap_system_parts(*, account_id: int) -> tuple[str, str]:
    """Системный промпт + dynamic_tail для чата по резюме.

    System — статичный шаблон `prompts/assistant/resume_gap_chat.md` (с подставленным
    `{{CANDIDATE_IDENTITY}}`), переиспользует `cache_prefix` как у vacancy/market_chat.
    Dynamic_tail — контекст аккаунта, собранный best-effort (каждый блок независимо деградирует,
    паттерн `_vacancy_system_parts`):

    1. Балл резюме + 4 фактора + слабые буллеты + недостающие концепты — `build_gap_report`
       (те же метрики, что владелец видит в левой панели «Резюме»).
    2. Критерии поиска + опыт + about + скиллы — `load_candidate_profile_enriched` (зарплата/
       форматы/грейды/приоритеты) + `gather_bio_material` (готовый блок должность/категории/
       зарплата/навыки/опыт).
    3. Топ-вакансии + funnel — `build_strengthen_context` (уже собирает gap + weak bullets +
       top-N вакансий + funnel в единый текст).
    4. Суммаризация рынка — `gather_situation_facts` + `build_situation_user_prompt` с таймаутом
       (как `_market_chat_system_parts`): воронка/гейты/деньги/шанс офферов.

    Возвращает (system_prompt, dynamic_tail). Без контекста (нет PG/резюме) — пустой tail,
    модель всё равно отвечает на общий вопрос про резюме.
    """
    from core.domains.market.situation import (
        _FACTS_TIMEOUT_S,
        build_situation_user_prompt,
        gather_situation_facts,
    )
    from core.domains.opportunities.prompt import (
        CANDIDATE_IDENTITY_TOKEN,
        load_candidate_identity,
    )
    from core.domains.profile.context import gather_bio_material
    from core.domains.profile.gap import build_gap_report
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    system_prompt = _resume_gap_template().replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )

    # 1. Балл + факторы + weak bullets (через build_gap_report — он же кормит левую панель).
    report: ResumeGapReport | None = None
    try:
        report = await build_gap_report(account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — best-effort, чат не падает без gap-отчёта
        logger.debug("resume_gap_chat: gap-отчёт недоступен: %s", exc)
    score_block = _resume_score_block(report)

    # 2 + 3. Био-материал (должность/категории/зарплата/навыки/опыт) + критерии поиска
    # (load_candidate_profile_enriched — salary/formats/grades/priorities/career hints) +
    # топ-вакансии + funnel (build_strengthen_context уже собирает это в единый текст).
    bio = ""
    criteria = ""
    strengthen = ""
    try:
        bio = gather_bio_material(resume_data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resume_gap_chat: био-материал недоступен: %s", exc)
    try:
        from core.domains.profile.profile import load_candidate_profile_enriched

        prof = await load_candidate_profile_enriched(account_id=account_id, data=resume_data)
        crit_lines: list[str] = []
        if prof.title:
            crit_lines.append(f"- Целевая должность: {prof.title}")
        if prof.specialization:
            crit_lines.append(f"- Специализация: {prof.specialization}")
        if prof.target_grades:
            crit_lines.append(f"- Целевой грейд: {', '.join(prof.target_grades)}")
        if prof.priorities:
            crit_lines.append(f"- Приоритеты: {', '.join(prof.priorities)}")
        if prof.key_skills:
            crit_lines.append(f"- Ключевые навыки: {', '.join(prof.key_skills)}")
        if prof.salary_min > 0:
            crit_lines.append(f"- Зарплата от: {prof.salary_min}")
        formats = []
        if prof.allows_remote:
            formats.append("удалёнка")
        if prof.allows_hybrid:
            formats.append("гибрид")
        if prof.allows_office:
            formats.append("офис")
        if formats:
            crit_lines.append(f"- Форматы: {', '.join(formats)}")
        if prof.role_kind:
            crit_lines.append(f"- Тип роли: {prof.role_kind}")
        criteria = "\n".join(crit_lines)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resume_gap_chat: профиль поиска недоступен: %s", exc)
    try:
        from core.domains.profile.context import build_strengthen_context

        ctx = await build_strengthen_context(account_id=account_id, report=report, data=resume_data)
        strengthen = ctx.text
    except Exception as exc:  # noqa: BLE001
        logger.debug("resume_gap_chat: контекст усиления/топ-вакансии недоступны: %s", exc)

    # 4. Суммаризация рынка (воронка/гейты/деньги/шанс офферов) — как в чате по рынку.
    market = ""
    try:
        facts = await asyncio.wait_for(
            gather_situation_facts(account_id=account_id),
            timeout=_FACTS_TIMEOUT_S,
        )
        from core.domains.profile.profile import load_candidate_profile_enriched

        situation_profile = await load_candidate_profile_enriched(
            account_id=account_id, data=resume_data
        )
        market = build_situation_user_prompt(
            facts,
            profile=situation_profile,
            target_companies=list(resume_data.search_criteria.target_companies or []),
        )
    except Exception as exc:  # noqa: BLE001 — рынок best-effort, не блокирует ответ
        logger.debug("resume_gap_chat: суммаризация рынка недоступна: %s", exc)

    # Полный текст резюме (markdown) — чтобы модель видела текущую версию целиком.
    resume_md = ""
    try:
        from core.domains.opportunities.prompt import load_resume

        resume_md = load_resume(data=resume_data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resume_gap_chat: markdown резюме недоступен: %s", exc)

    parts: list[str] = []
    if score_block:
        parts.append(score_block)
    if criteria:
        parts.append(f"## Критерии поиска\n\n{criteria}")
    if bio:
        parts.append(f"## Био-материал (должность/категории/зарплата/навыки/опыт)\n\n{bio}")
    if resume_md:
        parts.append(f"## Резюме кандидата (текущая версия, markdown)\n\n{resume_md}")
    if strengthen:
        parts.append(f"## Топ-вакансии и срез воронки (под них точим усиление)\n\n{strengthen}")
    if market:
        parts.append(f"## Ситуация на рынке (суммаризация из раздела «Рынок»)\n\n{market}")
    dynamic_tail = "\n\n".join(p for p in parts if p).strip()
    return system_prompt, dynamic_tail


@lru_cache(maxsize=1)
def _market_chat_template() -> str:
    """Сырой текст файла-промпта market_chat — кэш, диск не перечитываем на каждый вызов."""
    from core.domains.market.llm import MARKET_CHAT as _PROMPT_PATH

    path = Path(_PROMPT_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт market_chat не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


async def _market_chat_system_parts(*, account_id: int) -> tuple[str, str]:
    """Системный промпт + dynamic_tail для чата по ситуации на рынке.

    System — статичный шаблон `prompts/market/chat.md` (с подставленным `{{CANDIDATE_IDENTITY}}`),
    переиспользует `cache_prefix` как у vacancy/resume-gap. Dynamic_tail — факты аккаунта
    (воронка/гейты/деньги/отклик резюме/шанс офферов/активные офферы/источники/период), собранные
    через `gather_situation_facts`. Без фактов (нет заскоренных вакансий) — пустой tail, модель
    всё равно отвечает на общий вопрос про рынок/стратегию, но прямо скажет, что данных мало.

    Возвращает (system_prompt, dynamic_tail). Best-effort: сбой сбора фактов → пустой tail, чат не падает.
    """
    from core.domains.market.situation import (
        _FACTS_TIMEOUT_S,
        build_situation_user_prompt,
        gather_situation_facts,
    )
    from core.domains.opportunities.prompt import (
        CANDIDATE_IDENTITY_TOKEN,
        load_candidate_identity,
    )
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    system_prompt = _market_chat_template().replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )

    try:
        facts = await asyncio.wait_for(
            gather_situation_facts(account_id=account_id),
            timeout=_FACTS_TIMEOUT_S,
        )
        from core.domains.profile.profile import load_candidate_profile_enriched

        situation_profile = await load_candidate_profile_enriched(
            account_id=account_id, data=resume_data
        )
        dynamic_tail = build_situation_user_prompt(
            facts,
            profile=situation_profile,
            target_companies=list(resume_data.search_criteria.target_companies or []),
        )
    except Exception as exc:  # noqa: BLE001 — факты best-effort, чат не должен падать без них
        logger.debug("market_chat: факты недоступны, отвечаю без контекста: %s", exc)
        dynamic_tail = ""
    return system_prompt, dynamic_tail


@lru_cache(maxsize=1)
def _offers_chat_template() -> str:
    """Сырой текст файла-промпта offers_chat — кэш, диск не перечитываем на каждый вызов."""
    from core.domains.offers.llm import OFFERS_CHAT as _PROMPT_PATH

    path = Path(_PROMPT_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт offers_chat не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


async def _offers_chat_system_parts(*, account_id: int) -> tuple[str, str]:
    """Системный промпт + dynamic_tail для чата вкладки «Офферы».

    System — статичный шаблон `prompts/offers/chat.md` (с подставленным `{{CANDIDATE_IDENTITY}}`).
    Dynamic_tail — свежий снимок карточек и цели кандидата (`gather_offers_chat_tail`),
    собирается на каждый запрос: правка оффера видна в следующем вопросе.
    """
    from core.domains.offers.offers_chat_context import gather_offers_chat_tail
    from core.domains.opportunities.prompt import (
        CANDIDATE_IDENTITY_TOKEN,
        load_candidate_identity,
    )
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    system_prompt = _offers_chat_template().replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )
    try:
        dynamic_tail = await gather_offers_chat_tail(account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — факты best-effort, чат не должен падать без них
        logger.debug("offers_chat: факты недоступны, отвечаю без контекста: %s", exc)
        dynamic_tail = ""
    return system_prompt, dynamic_tail


async def _generate_follow_ups(
    question: str,
    answer: str,
    *,
    llm: ports.LlmPort | None = None,
) -> list[str]:
    """2-3 коротких клика продолжения диалога (п.3).

    Тесты подменяют порт одним фейком на весь `stream_answer`.
    Best-effort - любой сбой (включая кривой structured-ответ фейка) → пустой список.
    """
    if len(answer) < _FOLLOWUP_MIN_ANSWER_LEN:
        return []
    try:
        prompt = (
            "По вопросу и ответу ниже предложи 2-3 коротких (3-7 слов) реплики, которыми владелец "
            "мог бы продолжить разговор - уточнить, попросить пример, копнуть глубже по теме "
            "ответа. Каждая реплика - от первого лица, как будто её печатает сам владелец. "
            "Не повторяй вопрос. Без нумерации, без markdown.\n\n"
            f"Вопрос: {question}\n\nОтвет: {answer[:1500]}"
        )
        result = await (llm or ports.llm()).structured(
            "chat_followups",
            schema=_FollowUps,
            user=prompt,
            max_retries=1,
        )
        return [s.strip() for s in result.suggestions if s.strip()][:3]
    except Exception as exc:  # noqa: BLE001 — подсказки best-effort, не блокируют ответ
        logger.debug("chat: follow-up подсказки не сгенерированы: %s", exc)
        return []


async def stream_answer(
    payload: dict[str, Any],
    *,
    account_id: int,
    llm: ports.LlmPort | None = None,
    settings: CoreSettings | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Стрим ответа чата: события `{event, data}` → SSE A-14 (`part`/`progress`/`done`/`error`).

    `llm` подменяется в тестах (порт). `vacancy` / `resume_gap` / `hr_draft` — режимы
    из payload.
    """
    cfg = settings or get_settings()
    message = _extract_message(payload)
    attachment_ids = _extract_attachment_ids(payload)
    if not message and not attachment_ids:
        yield {"event": "error", "data": {"message": "пустое сообщение"}}
        yield {"event": "done", "data": {"status": "error"}}
        return

    vacancy = _vacancy_payload(payload)
    resume_gap = _is_resume_gap(payload)
    market_chat = _is_market_chat(payload)
    offers_chat = _is_offers_chat(payload)
    hr_draft = _is_hr_draft(payload) and vacancy is not None
    # Вложения — «Чаты · Агент», чат по рынку, чат по резюме и чат по офферам.
    # Не черновик HR (владелец правит текст сам) и не свободный чат без режима.
    if hr_draft or (vacancy is None and not market_chat and not resume_gap and not offers_chat):
        attachment_ids = []
    note_ids = _explicit_note_ids(payload)
    explicit_notes = await _explicit_notes_block(note_ids, account_id=account_id)
    reply_to_message_id = _extract_reply_to_message_id(payload)
    images, doc_text = await _load_current_attachments(attachment_ids, account_id=account_id)
    # L-11: system= + dynamic_tail (cache_prefix), history без system — иначе кэш не ставится.
    dynamic_tail = ""
    if hr_draft:
        assert vacancy is not None  # для type checker - обеспечено условием выше
        system_prompt = await _hr_draft_system_prompt(vacancy, message, account_id=account_id)
        feature_name = "hr_draft_chat"
        temperature = 0.5
        tier_override = str(payload.get("tier") or "").strip() or None
    elif vacancy is not None:
        system_prompt, dynamic_tail = await _vacancy_system_parts(
            vacancy, message, account_id=account_id
        )
        if reply_to_message_id is not None:
            quote_block = await _reply_quote_block(reply_to_message_id, account_id=account_id)
            if quote_block:
                dynamic_tail = f"{dynamic_tail}\n\n{quote_block}".strip()
        if doc_text:
            dynamic_tail = f"{dynamic_tail}\n\n{doc_text}".strip()
        if explicit_notes:
            dynamic_tail = f"{dynamic_tail}\n\n{explicit_notes}".strip()
        feature_name = "qa_vacancy"
        temperature = 0.4
        tier_override = str(payload.get("tier") or "").strip() or None
    elif resume_gap:
        system_prompt, dynamic_tail = await _resume_gap_system_parts(account_id=account_id)
        if reply_to_message_id is not None:
            quote_block = await _resume_reply_quote_block(
                reply_to_message_id, account_id=account_id
            )
            if quote_block:
                dynamic_tail = f"{dynamic_tail}\n\n{quote_block}".strip()
        if doc_text:
            dynamic_tail = f"{dynamic_tail}\n\n{doc_text}".strip() if dynamic_tail else doc_text
        if explicit_notes:
            dynamic_tail = (
                f"{dynamic_tail}\n\n{explicit_notes}".strip() if dynamic_tail else explicit_notes
            )
        feature_name = "resume_gap_chat"
        temperature = 0.4
        tier_override = str(payload.get("tier") or "").strip() or None
    elif market_chat:
        system_prompt, dynamic_tail = await _market_chat_system_parts(account_id=account_id)
        if reply_to_message_id is not None:
            quote_block = await _market_reply_quote_block(
                reply_to_message_id, account_id=account_id
            )
            if quote_block:
                dynamic_tail = f"{dynamic_tail}\n\n{quote_block}".strip()
        if doc_text:
            dynamic_tail = f"{dynamic_tail}\n\n{doc_text}".strip() if dynamic_tail else doc_text
        if explicit_notes:
            dynamic_tail = (
                f"{dynamic_tail}\n\n{explicit_notes}".strip() if dynamic_tail else explicit_notes
            )
        feature_name = "market_chat"
        temperature = 0.4
        tier_override = str(payload.get("tier") or "").strip() or None
    elif offers_chat:
        system_prompt, dynamic_tail = await _offers_chat_system_parts(account_id=account_id)
        if reply_to_message_id is not None:
            quote_block = await _offers_reply_quote_block(
                reply_to_message_id, account_id=account_id
            )
            if quote_block:
                dynamic_tail = f"{dynamic_tail}\n\n{quote_block}".strip()
        if doc_text:
            dynamic_tail = f"{dynamic_tail}\n\n{doc_text}".strip() if dynamic_tail else doc_text
        if explicit_notes:
            dynamic_tail = (
                f"{dynamic_tail}\n\n{explicit_notes}".strip() if dynamic_tail else explicit_notes
            )
        feature_name = "offers_chat"
        temperature = 0.4
        tier_override = str(payload.get("tier") or "").strip() or None
    else:
        system_prompt = await _load_prompt(cfg, account_id=account_id)
        dynamic_tail = explicit_notes
        feature_name = CHAT_AGENT
        temperature = 0.6
        tier_override = None

    if hr_draft:
        human_text = f"Напиши черновик сейчас: {message}."
    elif not message and attachment_ids:
        # Вложение(я) без сопроводительного текста — модели всё равно нужна реплика user (плана).
        human_text = "Прокомментируй приложенные вложения."
    else:
        human_text = message
    history = [] if hr_draft else _history_messages(payload)
    port = llm or ports.llm()

    yield {"event": "node_start", "data": {"node": "chat"}}

    parts: list[str] = []
    try:
        token_stream = port.stream(
            feature_name,
            system=system_prompt,
            dynamic_tail=dynamic_tail,
            messages=history,
            user=human_text,
            temperature=temperature,
            tier_override=tier_override,
            tags=("chat",),
            images=images,
        )
        async for piece in token_stream:
            parts.append(piece)
            yield {"event": "token", "data": {"text": piece, "node": "chat"}}
    except Exception as exc:  # noqa: BLE001 — конверт ошибки вместо падения стрима
        logger.warning("chat: генерация ответа провалилась: %s", exc)
        yield {"event": "error", "data": {"message": str(exc)}}
        yield {"event": "done", "data": {"status": "error"}}
        return

    answer = "".join(parts).strip()
    kind = (
        "черновик HR"
        if hr_draft
        else "по вакансии"
        if vacancy is not None
        else "разбор резюме"
        if resume_gap
        else "по ситуации рынка"
        if market_chat
        else "по офферам"
        if offers_chat
        else "свободный"
    )
    event(logger, "ЗАДАЧА", "chat (%s): «%.50s» → %d симв.", kind, message, len(answer))

    # Чат по вакансии — кладём обмен в единый разговор вакансии. Best-effort: нет PG → не пишем.
    # Черновик HR — исключение: не пишется в ленту (владелец правит и отправляет вручную).
    if vacancy is not None and answer and not hr_draft:
        vacancy_id = str(vacancy.get("vacancy_id") or "").strip()
        if vacancy_id:
            try:
                from core.domains.pipeline.hr_threads import append_llm_exchange

                await append_llm_exchange(
                    vacancy_id,
                    question=message,
                    answer=answer,
                    company=str(vacancy.get("company") or ""),
                    reply_to_message_id=reply_to_message_id,
                    attachment_ids=attachment_ids,
                    account_id=account_id,
                )
            except Exception as exc:  # noqa: BLE001 — персист best-effort, не валим ответ чата
                logger.warning("chat: обмен не записан в разговор: %s", exc)
    # Чат по резюме — пишем обе реплики в ленту аккаунта (resume_chat_messages). Best-effort:
    # нет PG → не падаем, просто реплики не сохранятся (персист вторичен к ответу).
    # reply_to_message_id/attachment_ids (паритет с чатом по рынку, миграция 0120).
    elif resume_gap and answer:
        try:
            from core.domains.assistant.attachments.service import link_to_resume_chat_message
            from core.domains.assistant.resume_chat import append_resume_chat

            user_msg = await append_resume_chat(
                account_id=account_id,
                role="user",
                content=message,
                reply_to_message_id=reply_to_message_id,
            )
            if attachment_ids and user_msg.id is not None:
                await link_to_resume_chat_message(
                    user_msg.id, attachment_ids, account_id=account_id
                )
            await append_resume_chat(account_id=account_id, role="assistant", content=answer)
        except Exception as exc:  # noqa: BLE001 — персист best-effort
            logger.warning("chat: реплики резюме-чата не сохранены: %s", exc)
    # Чат по ситуации на рынке — пишем обе реплики в market_chat_messages (замена бывшего блока
    # «Что сделать»): история переживает переход между разделами и перезагрузку. Best-effort.
    # reply_to_message_id/attachment_ids (2026-08-11, Заход 6 п.7) — паритет с чатом по вакансии.
    elif market_chat and answer:
        try:
            from core.domains.market.market_chat import append_market_chat

            user_msg = await append_market_chat(
                account_id=account_id,
                role="user",
                content=message,
                reply_to_message_id=reply_to_message_id,
            )
            if attachment_ids and user_msg.id is not None:
                from core.domains.assistant.attachments.service import link_to_market_chat_message

                await link_to_market_chat_message(
                    user_msg.id, attachment_ids, account_id=account_id
                )
            await append_market_chat(account_id=account_id, role="assistant", content=answer)
        except Exception as exc:  # noqa: BLE001 — персист best-effort
            logger.warning("chat: реплики чата по рынку не сохранены: %s", exc)

    elif offers_chat and answer:
        try:
            from core.domains.assistant.attachments.service import link_to_offers_chat_message
            from core.domains.offers.offers_chat import append_offers_chat

            user_msg = await append_offers_chat(
                account_id=account_id,
                role="user",
                content=message,
                reply_to_message_id=reply_to_message_id,
            )
            if attachment_ids and user_msg.id is not None:
                await link_to_offers_chat_message(
                    user_msg.id, attachment_ids, account_id=account_id
                )
            await append_offers_chat(account_id=account_id, role="assistant", content=answer)
        except Exception as exc:  # noqa: BLE001 — персист best-effort
            logger.warning("chat: реплики чата по офферам не сохранены: %s", exc)

    follow_ups: list[str] = []
    if answer and not resume_gap and not hr_draft and not market_chat and not offers_chat:
        follow_ups = await _generate_follow_ups(message, answer, llm=port)

    yield {
        "event": "result",
        "data": {"answer": answer, "follow_ups": follow_ups, "question": message},
    }
    yield {"event": "done", "data": {"status": "done"}}
