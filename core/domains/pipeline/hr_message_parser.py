"""LLM-анализ HR-переписки: намерение, дата собеса, статус воронки.

LLM-вызов идёт через порт `kernel.ports.llm().complete` (фича `hr_parse`);
схемы/funnel/время — из `core.*`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from core.domains.opportunities.anti_hallucination import (
    ANTI_HALLUCINATION_JSON,
    ANTI_HALLUCINATION_RULES,
)
from core.domains.pipeline.heuristic_hr import merge_heuristic
from core.domains.pipeline.hr_enrichment import (
    funnel_status_for_stage,
    infer_stage_type,
    is_valid_stage_type,
    parse_interview_stages,
    parse_salary_match,
)
from core.domains.pipeline.hr_identity import extract_hr_link_from_text, merge_hr_link
from core.domains.pipeline.models import HrMessageAnalysis, MessageIntent
from core.domains.pipeline.vacancy_links import (
    extract_primary_job_url,
    extract_primary_vacancy_id,
)
from core.domains.preparation.interview.timing import stage_status_from_datetime
from core.domains.preparation.models import InterviewStageType
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.schemas.funnel import (
    INTENT_TO_FUNNEL_STATUS,
    FunnelStatus,
    all_funnel_status_values,
    resolve_funnel_status,
)
from core.platform.observability import event

logger = logging.getLogger(__name__)

_MSK = timezone(timedelta(hours=3))

_SYSTEM_PROMPT = """\
Ты — ассистент по поиску работы. Анализируешь переписку с HR/рекрутёром на русском языке.

ВАЖНО: сообщение может быть из Telegram-лички (HR написал первым), без ссылки на hh.ru.
В этом случае извлеки компанию и должность из текста, подписи, домена email, названия агентства.

Сегодня: {today}

Верни ТОЛЬКО валидный JSON.

Поля:
- intent — одно из:
  * "hr_outreach" — HR/рекрутёр пишет первым, предлагает вакансию, знакомится (cold inbound)
  * "interview_scheduled" — назначено конкретное собеседование
  * "interview_rescheduled" — перенос собеса
  * "scheduling_request" — HR просит выбрать слот, время не зафиксировано
  * "rejection" — отказ
  * "offer" — оффер
  * "test_task" — тестовое задание
  * "follow_up" — повторное сообщение HR
  * "general" — прочее
  * "unknown" — непонятно
- company (str) — компания-работодатель (не путать с HR-агентством; если только агентство — укажи его)
- position (str) — должность / стек / роль
- vacancy_url (str) — ссылка на вакансию (hh.ru/vacancy/... или career/job URL компании), иначе ""
- salary_text (str) — вилка/ЗП если упомянута, иначе ""
- source ("hh"|"telegram"|"email"|"other") — откуда переписка
- interview_dt (str|null) — ISO 8601 +03:00 для interview_scheduled/rescheduled
- format ("online"|"offline"|"unknown")
- interviewer_name (str)
- contact (str) — t.me, @username, email, телефон рекрутёра
- hr_link (str) — канонический ключ HR (tg:@user / mail:…), если известен
- funnel_status (str) — одно из: {status_list}
- summary (str) — одно предложение (карточка / переписка)
- debrief_summary (str) — развёрнутые заметки после собеса: проект, стек, команда, вопросы, расхождения с резюме, что уточнить на техэтапе; пусто если только переписка HR
- salary_hr_range (str) — вилка/ЗП от HR (не из вакансии), иначе ""
- salary_match ("yes"|"no"|"unclear"|null) — укладывается ли в ожидания кандидата (~400k+)
- format_clarified (str) — remote/hybrid/office если HR уточнил, иначе ""
- team_size (str) — размер команды если упомянут, иначе ""
- stage_type ("hr_screening"|"live_coding"|"system_design"|"theory"|"soft_skills"|"manager"|"business_case"|"final"|null)
- interview_stages (array) — если несколько этапов: [{{"stage_type":"...", "scheduled_at":"ISO|null", "format":"online|offline|unknown", "status":"scheduled|completed", "notes":""}}]
  * status=completed если этап уже прошёл (дата в прошлом или явно «прошёл»)

Правила:
- HR написал в Telegram про вакансию без hh — intent=hr_outreach, source=telegram, funnel_status="{hr_conv}".
- Не оставляй company="Неизвестная компания" если в тексте есть хоть какое-то название.
- Если должность неясна — сформулируй из контекста (например "LLM Engineer (уточняется)").
- Если в переписке несколько сообщений — смотри на последнее по смыслу.
- Текст может быть ЗАМЕТКОЙ пользователя (не дословно от HR): «Hr ставила собес в Сбер на 21.05.2026 в 16:00» — извлеки дату, компанию, intent=interview_scheduled.
- Дата в прошлом — interview_dt, funnel_status={interview}, для прошедших этапов status=completed.
- Заметка пользователя после собеса (тезисы, диалог, «прошёл собес») — intent=interview_scheduled или general; заполни debrief_summary развёрнуто.
- «Давайте созвонимся» / «предлагаю созвон» без фиксированного времени — intent=scheduling_request, funnel_status="{hr_call}".
- HR прислал несколько слотов на выбор (27.05 11:00, 14:00…) без твоего выбора — intent=scheduling_request, interview_dt=null.
- Если кандидат в заметке указал прошедший собес с датой — intent=interview_scheduled, stage_type=manager если «руководитель».
- «Техническое собеседование в пятницу» — stage_type=live_coding, intent=interview_scheduled.
- «Финальное собеседование» / «финальный раунд» / «встреча с руководством после техэтапов» /
  «onsite» — stage_type=final, funnel_status="{final}".
- jazz.sberbank.ru / zoom / meet — format=online, ссылку в contact.

{anti_hallucination}
{anti_json}
"""


async def _resolve_stage_type(text: str, parsed: dict) -> InterviewStageType:
    """stage_type от основного парсера, если валиден; иначе дешёвый LLM-резолв
    (`stage_type_llm.py`), а на его сбой — regex-fallback `infer_stage_type`."""
    raw = (parsed.get("stage_type") or "").strip()
    if is_valid_stage_type(raw):
        return raw  # type: ignore[return-value]

    from core.domains.pipeline.stage_type_llm import resolve_stage_type_llm

    try:
        resolved = await resolve_stage_type_llm(text)
    except Exception as exc:
        logger.warning("stage_type LLM resolve error: %s", exc)
        resolved = None

    if resolved is not None:
        return resolved[0]

    return infer_stage_type(text, parsed)


async def _postprocess(parsed: dict, raw_text: str) -> HrMessageAnalysis:
    intent: MessageIntent = parsed.get("intent", "unknown")  # type: ignore[assignment]
    if intent not in INTENT_TO_FUNNEL_STATUS and intent not in (
        "general",
        "unknown",
    ):
        intent = "unknown"

    llm_url = (parsed.get("vacancy_url") or "").strip()
    vacancy_id = extract_primary_vacancy_id(raw_text, llm_url)
    vacancy_url = extract_primary_job_url(raw_text, llm_url)

    source = parsed.get("source", "telegram")
    if source not in ("hh", "telegram", "email", "other", "habr"):
        source = "telegram" if not vacancy_id else "hh"
    if vacancy_id.startswith("habr_"):
        source = "habr"

    interview_dt: datetime | None = None
    if parsed.get("interview_dt"):
        with contextlib.suppress(Exception):
            interview_dt = datetime.fromisoformat(parsed["interview_dt"])

    funnel_status = resolve_funnel_status(
        (parsed.get("funnel_status") or "").strip(),
        intent,
    )

    company = (parsed.get("company") or "").strip() or "Неизвестная компания"
    position = (parsed.get("position") or "").strip() or "Неизвестная позиция"

    # Cold inbound: если есть компания, но нет hh — всё равно ведём воронку
    if not funnel_status and not vacancy_id and company != "Неизвестная компания":
        funnel_status = FunnelStatus.SCREENING
        if intent in ("unknown", "general"):
            intent = "hr_outreach"

    if intent in ("interview_scheduled", "interview_rescheduled") and interview_dt:
        if interview_dt.tzinfo is None:
            interview_dt = interview_dt.replace(tzinfo=_MSK)
        if not funnel_status:
            funnel_status = FunnelStatus.SCREENING

    fmt = parsed.get("format", "unknown")
    if fmt not in ("online", "offline", "unknown"):
        fmt = "unknown"

    stage_type = await _resolve_stage_type(raw_text, parsed)
    interview_stages = parse_interview_stages(parsed)
    interview_stages = [
        s.model_copy(
            update={
                "status": stage_status_from_datetime(s.scheduled_at, s.status),
            }
        )
        for s in interview_stages
    ]

    debrief_summary = (parsed.get("debrief_summary") or "").strip()
    if (
        not debrief_summary
        and len(raw_text) > 350
        and re.search(
            r"собес|интервью|прошёл|прошла|прошел|прошла|этап|диалог|руковод",
            raw_text,
            re.I,
        )
    ):
        debrief_summary = raw_text.strip()[:12000]

    salary_hr_range = (parsed.get("salary_hr_range") or parsed.get("salary_text") or "").strip()
    salary_match = parse_salary_match(parsed.get("salary_match"))
    format_clarified = (parsed.get("format_clarified") or "").strip()
    team_size = (parsed.get("team_size") or "").strip()

    if intent in ("interview_scheduled", "interview_rescheduled"):
        funnel_status = funnel_status_for_stage(stage_type)

    hr_link = merge_hr_link(
        (parsed.get("hr_link") or "").strip(),
        (parsed.get("contact") or "").strip(),
        extract_hr_link_from_text(raw_text),
    )

    return HrMessageAnalysis(
        intent=intent,
        company=company,
        position=position,
        vacancy_url=vacancy_url,
        vacancy_id=vacancy_id,
        interview_dt=interview_dt,
        format=fmt,
        interviewer_name=parsed.get("interviewer_name") or "",
        contact=parsed.get("contact") or "",
        hr_link=hr_link,
        salary_text=(parsed.get("salary_text") or "").strip(),
        salary_hr_range=salary_hr_range,
        salary_match=salary_match,
        format_clarified=format_clarified,
        team_size=team_size,
        stage_type=stage_type,
        interview_stages=interview_stages,
        source=source,
        funnel_status=funnel_status or "",
        summary=parsed.get("summary") or "",
        debrief_summary=debrief_summary,
        raw_text=raw_text,
    )


def _parse_llm_json(raw: str) -> dict:
    """Парсинг JSON из ответа LLM с несколькими fallback-стратегиями."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    candidates = [text]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group())
        candidates.append(re.sub(r",\s*}", "}", match.group()))
        candidates.append(re.sub(r",\s*]", "]", match.group()))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return {}


async def _call_llm(text: str, system: str) -> dict:
    raw = await ports.llm().complete(
        "hr_parse",
        system=system,
        user=text,
        temperature=0.0,
    )
    return _parse_llm_json(raw)


async def parse_hr_message(text: str) -> HrMessageAnalysis:
    """Анализирует HR-переписку и возвращает структурированный результат."""
    today = datetime.now(tz=_MSK).strftime("%Y-%m-%d (%A, MSK)")
    status_list = ", ".join(f'"{s}"' for s in all_funnel_status_values())
    system = _SYSTEM_PROMPT.format(
        today=today,
        status_list=status_list,
        hr_conv=FunnelStatus.SCREENING,
        hr_call=FunnelStatus.SCREENING,
        interview=FunnelStatus.SCREENING,
        final=FunnelStatus.FINAL,
        anti_hallucination=ANTI_HALLUCINATION_RULES,
        anti_json=ANTI_HALLUCINATION_JSON,
    )

    parsed: dict = {}
    try:
        parsed = await _call_llm(text, system)
    except LlmError as e:
        logger.warning("hr_message_parser: LLM error (primary): %s", e)

    if not parsed:
        try:
            retry_system = system + "\n\nКРИТИЧНО: ответ — один JSON-объект, без текста до/после."
            parsed = await _call_llm(text, retry_system)
        except Exception as e:
            logger.warning("hr_message_parser: LLM error (retry): %s", e)

    parsed = merge_heuristic(parsed, text)
    result = await _postprocess(parsed, text)

    if result.vacancy_id and not result.funnel_status.strip():
        from core.domains.pipeline.funnel_status_llm import resolve_funnel_status_llm

        try:
            status, llm_reason = await resolve_funnel_status_llm(
                hh_status_raw=text[:300],
                company=result.company,
                title=result.position,
                current_status=None,
                extra_context=f"intent={result.intent}; telegram HR",
                vacancy_id=result.vacancy_id,
            )
            note = result.summary or ""
            if llm_reason:
                note = f"{note}; LLM: {llm_reason}".strip("; ")
            result = result.model_copy(
                update={"funnel_status": status, "summary": note or llm_reason}
            )
        except Exception as exc:
            logger.warning("HR funnel_status LLM fallback: %s", exc)
            if not result.funnel_status:
                result = result.model_copy(update={"funnel_status": FunnelStatus.SCREENING})

    if not result.should_update_funnel:
        logger.warning(
            "HR parse: funnel skip intent=%s company=%s status=%s",
            result.intent,
            result.company,
            result.funnel_status,
        )
    event(
        logger,
        "LLM",
        "hr_parse: intent=%s статус=%s дата_собеса=%s",
        result.intent,
        result.funnel_status or "-",
        "есть" if result.interview_dt else "нет",
        intent=result.intent,
        funnel_status=result.funnel_status,
        has_interview_dt=bool(result.interview_dt),
        stage_type=result.stage_type,
    )
    return result
