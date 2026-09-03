"""Разбиение пачки HR-сообщений на смысловые сегменты (воронка / календарь / ответ).

S10 принёс сюда только детектор `detect_self_debrief` (заметки кандидата после своего собеса).
S11 довёз полный HR-сегментатор: `segment_hr_messages` (1 LLM-вызов через порт `kernel.ports.llm()`)
плюс эвристический fallback. Теперь весь сегментатор живёт здесь, backend-free.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from core.domains.opportunities.enrichment import merge_enrichment
from core.domains.opportunities.jobs import find_vacancy_id_by_company
from core.domains.pipeline.models import (
    HrMessageSegment,
    HrSegmentationResult,
    SegmentAction,
    SegmentKind,
)
from core.domains.preparation.interview import analyze_debrief, load_record
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

_DEBRIEF_LLM_FAIL = (LlmError,)

_VACANCY_RE = re.compile(r"(?:hh\.ru/vacancy/|ваканси[июяе]\s+)(\d{6,12})", re.I)
_COMPANY_HINT_RE = re.compile(
    r"(?:в\s+|с\s+|собес\s+(?:в|с)\s+|после\s+(?:собеса|интервью)\s+(?:в|с)\s+)"
    r"([А-ЯA-Z][\w\-А-Яа-я]{2,30})",
)

_MAX_HEURISTIC_PARTS = 4

_KIND_TO_DEFAULT_ACTIONS: dict[SegmentKind, list[SegmentAction]] = {
    "rejection": ["rejection", "sheets"],
    "scheduling": ["sheets", "calendar"],
    "hr_questions": ["reply"],
    "outreach": ["sheets"],
    "status_update": ["sheets"],
    "info": [],
}

_SEGMENT_SYSTEM = """\
Ты разбиваешь переписку с HR на смысловые сегменты для автоматизации.

Вход: одна пачка пересланных сообщений (может быть длинной). Это ОДИН диалог, не разбивай по каждой строке.

Верни ТОЛЬКО JSON:
{{
  "segments": [
    {{
      "kind": "rejection|scheduling|hr_questions|outreach|status_update|info",
      "text": "релевантный фрагмент (можно сжать, но сохрани даты/имена)",
      "actions": ["sheets"|"calendar"|"reply"|"rejection"],
      "summary": "одно предложение"
    }}
  ]
}}

Правила:
- rejection — явный отказ → ["rejection","sheets"]
- scheduling — слоты/дата собеса/созвона → ["sheets","calendar"] если есть конкретная дата/время, иначе ["sheets"]
- hr_questions — вопросы к кандидату → ["reply"] (не создавай отдельный сегмент на каждый вопрос)
- outreach — первое знакомство / предложение вакансии → ["sheets"] один раз на всю пачку
- status_update — оффер, тестовое → ["sheets"]
- info — без действий → []

КРИТИЧНО: 1–4 сегмента на всю пачку. НЕ по одному сегменту на каждое короткое сообщение.
Если в пачке и слоты на собес, и приветствие — максимум 2 сегмента: outreach + scheduling.
"""


def _normalize_kind(raw: str) -> SegmentKind | None:
    k = (raw or "").strip().lower()
    allowed: tuple[SegmentKind, ...] = (
        "rejection",
        "scheduling",
        "hr_questions",
        "outreach",
        "status_update",
        "info",
    )
    if k in allowed:
        return k  # type: ignore[return-value]
    aliases = {
        "questions": "hr_questions",
        "question": "hr_questions",
        "interview": "scheduling",
        "calendar": "scheduling",
        "call": "scheduling",
        "reply": "hr_questions",
        "decline": "rejection",
    }
    return aliases.get(k)  # type: ignore[return-value]


def _normalize_actions(raw: list | None, kind: SegmentKind) -> list[SegmentAction]:
    allowed: tuple[SegmentAction, ...] = ("sheets", "calendar", "reply", "rejection")
    out: list[SegmentAction] = []
    if isinstance(raw, list):
        for item in raw:
            a = (str(item) or "").strip().lower()
            if a in allowed and a not in out:
                out.append(a)  # type: ignore[arg-type]
    if not out:
        out = list(_KIND_TO_DEFAULT_ACTIONS.get(kind, []))
    return out


_rejection_re = re.compile(
    r"отказ|к\s+сожалению|не\s+можем\s+продолж|не\s+готовы|"
    r"выбрали\s+другого|other\s+candidates|не\s+подошл",
    re.I,
)
_sched_re = re.compile(
    r"собес|интервью|созвон|встреч|zoom|meet\.google|jazz\.|"
    r"\d{1,2}\.\d{1,2}(?:\.\d{2,4})?",
    re.I,
)
_question_re = re.compile(r"\?|подскажите|уточните|скажите|готовы\s+ли", re.I)

# self-debrief: текст от 1 лица + явный признак прошедшего собеса
_first_person_re = re.compile(
    r"\b(я\s+(?:ответил|сказал|объясн|рассказал|показал|сделал|"
    r"справ|запутал|не\s+смог|забыл|вспомн)|меня\s+спросил|мне\s+задал|"
    r"мы\s+обсужд|спросили\s+(?:меня|про|как)|я\s+думаю,?\s+что\s+(?:провал|плохо|"
    r"норм|неплохо|хорошо))",
    re.I,
)
_past_interview_re = re.compile(
    r"(после\s+(?:собес|интервью|созвон|скрининг|техничк)|"
    r"прош(?:ёл|ла|ло|ли)\s+(?:собес|интервью|созвон|скрининг|техничк|финал)|"
    r"был(?:а|и)?\s+на\s+(?:собес|интервью|созвон|скрининг|техничк|финал)|"
    r"была\s+техничк|"
    r"закончил(?:ся|и|ась)\s+(?:собес|интервью|созвон|скрининг|техничк)|"
    r"(?:собес|интервью|техничк|скрининг)\s+прош(?:ёл|ла|ло)|"
    r"только\s+что\s+(?:с|после)\s+(?:собес|интервью|созвон|скрининг)|"
    r"debrief|дебриф|разбор\s+собес)",
    re.I,
)


def detect_self_debrief(text: str) -> bool:
    """Эвристика: похоже на заметки кандидата после своего собеса.

    True требует одновременно:
    - устойчивого 1-лица («я ответил», «меня спросили»),
    - явного маркера прошедшего собеса.
    Этого достаточно, чтобы отсечь HR-переписку (где обычно 3-е лицо или вопросы).
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < 80:
        return False
    if not _first_person_re.search(stripped):
        return False
    return bool(_past_interview_re.search(stripped))


def _classify_chunk(part: str) -> HrMessageSegment:
    if _rejection_re.search(part):
        return HrMessageSegment(
            kind="rejection",
            text=part,
            actions=["rejection", "sheets"],
            summary="Отказ от работодателя",
        )
    if _sched_re.search(part):
        return HrMessageSegment(
            kind="scheduling",
            text=part,
            actions=["sheets", "calendar"],
            summary="Планирование собеседования/созвона",
        )
    if _question_re.search(part):
        return HrMessageSegment(
            kind="hr_questions",
            text=part,
            actions=["reply"],
            summary="Вопросы от HR",
        )
    return HrMessageSegment(
        kind="outreach",
        text=part,
        actions=["sheets"],
        summary="Переписка с HR",
    )


def _merge_segments(segments: list[HrMessageSegment]) -> list[HrMessageSegment]:
    """Схлопнуть однотипные сегменты (несколько outreach → один)."""
    if not segments:
        return segments
    order: list[SegmentKind] = [
        "rejection",
        "scheduling",
        "hr_questions",
        "outreach",
        "status_update",
        "info",
    ]
    by_kind: dict[SegmentKind, HrMessageSegment] = {}
    for seg in segments:
        prev = by_kind.get(seg.kind)
        if prev is None:
            by_kind[seg.kind] = seg
            continue
        merged_text = f"{prev.text}\n\n{seg.text}".strip()
        actions = list(dict.fromkeys(prev.actions + seg.actions))
        summary = prev.summary or seg.summary
        by_kind[seg.kind] = HrMessageSegment(
            kind=seg.kind,
            text=merged_text[:8000],
            actions=actions,
            summary=summary,
        )
    return [by_kind[k] for k in order if k in by_kind]


def _heuristic_segments(text: str) -> list[HrMessageSegment]:
    """Fallback без LLM: для пачки пересылки — один проход по всему тексту."""
    stripped = text.strip()
    parts = [p.strip() for p in re.split(r"\n---\n|\n\n---\n\n", stripped) if p.strip()]

    if len(parts) > _MAX_HEURISTIC_PARTS:
        return _merge_segments([_classify_chunk(stripped)])

    if len(parts) <= 1:
        return [_classify_chunk(stripped)]

    classified = [_classify_chunk(p) for p in parts]
    return _merge_segments(classified)


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


def _parse_segments(data: dict, fallback_text: str) -> HrSegmentationResult:
    raw_list = data.get("segments")
    if not isinstance(raw_list, list) or not raw_list:
        segs = _heuristic_segments(fallback_text)
        return HrSegmentationResult(segments=segs, combined_context=fallback_text)

    segments: list[HrMessageSegment] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        kind = _normalize_kind(str(item.get("kind", "")))
        text = (item.get("text") or "").strip()
        if not kind or not text:
            continue
        actions = _normalize_actions(item.get("actions"), kind)
        segments.append(
            HrMessageSegment(
                kind=kind,
                text=text,
                actions=actions,
                summary=(item.get("summary") or "").strip(),
            )
        )

    segments = _heuristic_segments(fallback_text) if not segments else _merge_segments(segments)

    return HrSegmentationResult(segments=segments, combined_context=fallback_text)


async def segment_hr_messages(text: str) -> HrSegmentationResult:
    """Разбить пачку HR-сообщений на сегменты с целевыми действиями (1 LLM-вызов)."""
    stripped = text.strip()
    if not stripped:
        return HrSegmentationResult(segments=[], combined_context="")

    self_debrief = detect_self_debrief(stripped)
    if self_debrief:
        # debrief — не HR-переписка, сегментацию не делаем, оркестратор разрулит сам
        return HrSegmentationResult(
            segments=[],
            combined_context=stripped,
            is_self_debrief=True,
        )

    if len(stripped) < 120 and "---" not in stripped:
        h = _heuristic_segments(stripped)
        if len(h) == 1:
            return HrSegmentationResult(segments=h, combined_context=stripped)

    try:
        raw = await ports.llm().complete(
            "hr_segment",
            system=_SEGMENT_SYSTEM,
            user=stripped,
            temperature=0.0,
        )
        data = _parse_llm_json(raw)
        result = _parse_segments(data, stripped)
        if result.segments:
            event(
                logger,
                "LLM",
                "HR segments: %d → %s",
                len(result.segments),
                [(s.kind, s.actions) for s in result.segments],
                segments=len(result.segments),
                kinds=[s.kind for s in result.segments],
            )
            return result
    except LlmError as e:
        logger.warning("hr_segmenter: LLM error: %s", e)

    return HrSegmentationResult(
        segments=_heuristic_segments(stripped),
        combined_context=stripped,
    )


# ---- Self-debrief: resolve vacancy + разбор транскрипта (порт `bot_app.services.debrief_orchestrator`,
# перенесено в DR-3b — единственный оставшийся потребитель self-debrief-цепочки из forwarded.py) ----


@dataclass
class DebriefResolveResult:
    vacancy_id: str | None
    via: str  # "explicit_url" | "company_guess" | "none"
    guessed_company: str = ""


async def resolve_vacancy_for_debrief(text: str, *, account_id: int) -> DebriefResolveResult:
    """Попытаться вытащить vacancy_id из текста.

    1) Прямая ссылка hh.ru/vacancy/<id> или «вакансия 12345678».
    2) Догадка компании → последняя оценённая вакансия с этой компанией (PG).
    """
    m = _VACANCY_RE.search(text)
    if m:
        return DebriefResolveResult(vacancy_id=m.group(1), via="explicit_url")

    guess = _COMPANY_HINT_RE.search(text)
    if guess:
        company = guess.group(1).strip(" .,;:-")
        vid = await find_vacancy_id_by_company(company, account_id=account_id)
        if vid:
            return DebriefResolveResult(
                vacancy_id=vid, via="company_guess", guessed_company=company
            )
        return DebriefResolveResult(vacancy_id=None, via="none", guessed_company=company)

    return DebriefResolveResult(vacancy_id=None, via="none")


async def run_debrief(
    vacancy_id: str,
    transcript: str,
    *,
    stage_label: str = "",
    interview_id: int | None = None,
    account_id: int,
) -> dict:
    """Разобрать транскрипт и сохранить сводку в enrichment. Возвращает dict-ответ для хендлера."""
    record = await load_record(vacancy_id, account_id=account_id)
    if record is None:
        return {"error": "not_found"}

    try:
        analysis = await analyze_debrief(
            record, transcript, account_id=account_id, stage_label=stage_label
        )
    except ValueError as exc:
        return {"error": "bad_request", "detail": str(exc)}
    except _DEBRIEF_LLM_FAIL as exc:
        logger.warning("debrief LLM: %s", exc)
        return {"error": "llm", "detail": str(exc)}

    try:
        await merge_enrichment(
            vacancy_id, interview_debrief=analysis.summary, account_id=account_id
        )
    except Exception as exc:  # noqa: BLE001 — персист сводки best-effort, разбор уже готов
        logger.warning("debrief: enrichment merge не удался (%s): %s", vacancy_id, exc)

    return {
        "analysis": analysis.model_dump(mode="json"),
        "interview_id": interview_id,
        "sheets_synced": True,
        "sheets_error": None,
    }
