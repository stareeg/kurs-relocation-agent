"""Regex-эвристики, когда LLM не справился или текст — заметки пользователя (порт S11).

Порт `bot.utils.heuristic_hr`: таксономия этапов из `core.domains.preparation.models`, статусы из
`core.kernel.schemas.funnel`, тип этапа — `core.domains.pipeline.hr_enrichment.infer_stage_type`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core.domains.pipeline.hr_enrichment import infer_stage_type
from core.domains.preparation.models import STAGE_TO_FUNNEL_STATUS
from core.kernel.schemas.funnel import FunnelStatus

_MSK = timezone(timedelta(hours=3))

_DATE_TIME_RE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:в|@|,)?\s*(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)
_DATE_ONLY_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

_COMPANY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bсбер(?:банк)?\b", re.I), "Сбер"),
    (re.compile(r"\bsberbank\b", re.I), "Сбер"),
    (re.compile(r"jazz\.sberbank\.ru", re.I), "Сбер"),
    (re.compile(r"\bяндекс\b", re.I), "Яндекс"),
    (re.compile(r"\bvk\b", re.I), "VK"),
    (re.compile(r"\bтинькофф\b", re.I), "Тинькофф"),
    (re.compile(r"\bальфа[\s-]?банк\b", re.I), "Альфа-Банк"),
    (re.compile(r"\bмтс\b", re.I), "МТС"),
]

_INTERVIEW_KW = re.compile(r"собес(?:едование)?|интервью|встреч[ау]", re.I)
_CALL_KW = re.compile(
    r"созвон(?:имся|иться|)?|позвон(?:им|ить|)|"
    r"давайте\s+(?:на\s+)?(?:созвон|звонок|call)|"
    r"hr[\s-]?звонок|созвонимся",
    re.I,
)
_MEETING_URL_RE = re.compile(r"https?://[^\s]+", re.I)
_REJECTION_KW = re.compile(
    r"отказ|к\s+сожалению|не\s+можем\s+продолж|не\s+готовы|"
    r"выбрали\s+другого|other\s+candidates|не\s+подошл|"
    r"не\s+смогли\s+предложить",
    re.I,
)


def _parse_dt(text: str) -> datetime | None:
    m = _DATE_TIME_RE.search(text)
    if m:
        d, mo, y, h, mi = map(int, m.groups())
        try:
            return datetime(y, mo, d, h, mi, tzinfo=_MSK)
        except ValueError:
            pass
    m = _DATE_ONLY_RE.search(text)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return datetime(y, mo, d, 10, 0, tzinfo=_MSK)
        except ValueError:
            pass
    return None


def _parse_company(text: str) -> str:
    for pat, name in _COMPANY_PATTERNS:
        if pat.search(text):
            return name
    m = re.search(r"(?:в|@)\s+([А-ЯA-ZЁ][а-яa-zё\-]+(?:\s+[А-ЯA-ZЁ][а-яa-zё\-]+)?)", text)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in ("hr", "telegram", "сбер"):
            return candidate
    return ""


def _parse_position(text: str) -> str:
    lower = text.lower()
    if "питон" in lower or "python" in lower:
        return "Python (техническое собеседование)"
    if "llm" in lower:
        return "LLM Engineer"
    if _INTERVIEW_KW.search(text):
        return "Собеседование (уточняется)"
    return ""


def _parse_meeting_url(text: str) -> str:
    m = _MEETING_URL_RE.search(text)
    return m.group(0) if m else ""


def heuristic_extract(text: str) -> dict:
    """Достаёт поля из текста/заметок пользователя."""
    result: dict = {}
    dt = _parse_dt(text)
    if dt:
        result["interview_dt"] = dt.isoformat()
        result["intent"] = "interview_scheduled"
        result["funnel_status"] = FunnelStatus.SCREENING

    company = _parse_company(text)
    if company:
        result["company"] = company

    position = _parse_position(text)
    if position:
        result["position"] = position

    url = _parse_meeting_url(text)
    if url:
        result["meeting_url"] = url
        if "jazz" in url.lower() or "zoom" in url.lower() or "meet" in url.lower():
            result["format"] = "online"

    if _INTERVIEW_KW.search(text) and "intent" not in result:
        result["intent"] = "interview_scheduled"
        result["funnel_status"] = FunnelStatus.SCREENING

    if _REJECTION_KW.search(text):
        result["intent"] = "rejection"
        result["funnel_status"] = FunnelStatus.REJECTED

    if _CALL_KW.search(text) and "intent" not in result:
        result["intent"] = "scheduling_request"
        result["funnel_status"] = FunnelStatus.SCREENING

    stage_type = infer_stage_type(text, result)
    if stage_type:
        result["stage_type"] = stage_type
        if result.get("intent") in ("interview_scheduled", "interview_rescheduled", None) and (
            _INTERVIEW_KW.search(text) or dt
        ):
            result["intent"] = result.get("intent") or "interview_scheduled"
            if stage_type != "hr_screening":
                result["funnel_status"] = STAGE_TO_FUNNEL_STATUS.get(
                    stage_type, FunnelStatus.SCREENING
                )
            elif not result.get("funnel_status"):
                result["funnel_status"] = FunnelStatus.SCREENING

    if company or _INTERVIEW_KW.search(text) or _CALL_KW.search(text):
        result["source"] = "telegram"

    return result


def merge_heuristic(parsed: dict, raw_text: str) -> dict:
    """Дополняет LLM-ответ эвристиками (не перезаписывает непустые поля LLM)."""
    h = heuristic_extract(raw_text)
    out = dict(parsed)

    for key in ("company", "position", "funnel_status", "intent", "format", "source"):
        if not (out.get(key) or "").strip() and h.get(key):
            out[key] = h[key]

    if not out.get("interview_dt") and h.get("interview_dt"):
        out["interview_dt"] = h["interview_dt"]

    if h.get("meeting_url"):
        contact = (out.get("contact") or "").strip()
        if h["meeting_url"] not in contact:
            out["contact"] = f"{contact} {h['meeting_url']}".strip()

    if out.get("intent") in (None, "", "unknown") and h.get("intent"):
        out["intent"] = h["intent"]
    if not (out.get("funnel_status") or "").strip() and h.get("funnel_status"):
        out["funnel_status"] = h["funnel_status"]

    if (out.get("company") or "").strip() in ("", "Неизвестная компания") and h.get("company"):
        out["company"] = h["company"]

    if (out.get("position") or "").strip() in ("", "Неизвестная позиция") and h.get("position"):
        out["position"] = h["position"]

    return out
