"""Привязка HR-переписки к vacancy_id, hr_link и статусу воронки (порт S11).

Порт `bot.services.hr_vacancy_resolve` на core-репозитории (async): registry HR↔вакансия —
`core.domains.pipeline.hr_registry`, поиск вакансии — `core.domains.opportunities.jobs` (Postgres, источник истины), без
backend/SQLite. `resolve_hr_vacancy` теперь корутина (зовётся из async `apply_hr_actions`).
"""

from __future__ import annotations

import re

from core.domains.opportunities.jobs import find_vacancy_id_by_company, get_job_by_vacancy_id
from core.domains.pipeline.hr_identity import extract_hr_link_from_text, merge_hr_link
from core.domains.pipeline.hr_registry import register_hr_vacancy_link, resolve_vacancy_id_for_hr
from core.domains.pipeline.models import HrMessageAnalysis
from core.domains.pipeline.vacancy_links import listing_url_for_vacancy_id
from core.kernel.schemas.funnel import FunnelStatus, funnel_status_rank

_COMPANY_ALIASES: dict[str, frozenset[str]] = {
    "сбер": frozenset({"сбер", "сбербанк", "sber", "sberbank", "паосбербанк", "пао сбербанк"}),
    "яндекс": frozenset({"яндекс", "yandex"}),
    "тинькофф": frozenset({"тинькофф", "tinkoff", "тбанк", "t-bank"}),
    "альфа": frozenset({"альфа", "альфабанк", "alfa", "alfa-bank"}),
    "мтс": frozenset({"мтс", "mts"}),
}


def _norm_company(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def _company_key(s: str) -> str:
    n = _norm_company(s)
    for key, aliases in _COMPANY_ALIASES.items():
        if any(a in n or n in a for a in aliases):
            return key
    return n[:24]


def companies_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ka, kb = _company_key(a), _company_key(b)
    if ka and kb and ka == kb:
        return True
    na, nb = _norm_company(a), _norm_company(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def attach_hr_link(analysis: HrMessageAnalysis) -> HrMessageAnalysis:
    link = merge_hr_link(
        analysis.hr_link,
        analysis.contact,
        extract_hr_link_from_text(analysis.raw_text),
    )
    if link and link != analysis.hr_link:
        return analysis.model_copy(update={"hr_link": link})
    return analysis


async def _vacancy_id_conflicts_with_company(
    analysis: HrMessageAnalysis, *, account_id: int
) -> bool:
    """True только если id в Postgres явно от другой компании."""
    if not analysis.vacancy_id:
        return False
    if analysis.company in ("", "Неизвестная компания"):
        return False
    job = await get_job_by_vacancy_id(analysis.vacancy_id, account_id=account_id)
    if job is None or not job.company:
        return False
    return not companies_match(analysis.company, job.company)


async def resolve_hr_vacancy(analysis: HrMessageAnalysis, *, account_id: int) -> HrMessageAnalysis:
    """Согласовать vacancy_id + hr_link и проставить уверенность привязки.

    - hh-ссылка в сообщении — главный ключ вакансии → confidence 1.0;
    - hr_link → vacancy_id из registry → confidence 0.9;
    - find_vacancy_id_by_company (эвристика) → confidence 0.5 (бот не пишет в воронку, просит
      подтверждения).
    """
    analysis = attach_hr_link(analysis)
    company = analysis.company
    position = analysis.position
    hr_key = analysis.hr_link

    if await _vacancy_id_conflicts_with_company(analysis, account_id=account_id):
        analysis = analysis.model_copy(update={"vacancy_id": "", "vacancy_url": ""})

    if analysis.vacancy_id:
        # vacancy_id уже был в analysis — пришёл из ссылки в тексте (hh/habr).
        analysis = analysis.model_copy(
            update={"resolve_confidence": 1.0, "resolve_via": "url_in_text"}
        )

    if not analysis.vacancy_id and hr_key:
        vid = await resolve_vacancy_id_for_hr(
            hr_key=hr_key,
            company=company,
            position=position,
            preferred_vacancy_id="",
            account_id=account_id,
        )
        if vid:
            analysis = analysis.model_copy(
                update={
                    "vacancy_id": vid,
                    "vacancy_url": listing_url_for_vacancy_id(vid),
                    "resolve_confidence": 0.9,
                    "resolve_via": "hr_link_registry",
                },
            )

    if not analysis.vacancy_id and company not in ("", "Неизвестная компания"):
        vid = await find_vacancy_id_by_company(company, account_id=account_id)
        if vid:
            analysis = analysis.model_copy(
                update={
                    "vacancy_id": vid,
                    "vacancy_url": listing_url_for_vacancy_id(vid),
                    "resolve_confidence": 0.5,
                    "resolve_via": "company_search",
                },
            )

    if analysis.vacancy_id and hr_key and analysis.resolve_confidence >= 0.7:
        # Только подтверждённые связки записываем в registry.
        await register_hr_vacancy_link(
            hr_key=hr_key,
            vacancy_id=analysis.vacancy_id,
            company=company,
            position=position,
            hr_link=hr_key,
            account_id=account_id,
        )

    return analysis


def ensure_engaged_funnel_status(analysis: HrMessageAnalysis) -> HrMessageAnalysis:
    """Статус на «Отклики»: cold hh → «Скрининг», слоты после отклика → «Отклик»."""
    if analysis.intent == "rejection":
        return analysis

    text = (analysis.raw_text or "").lower()
    applied_markers = ("отклик", "откликнули", "отправил резюме", "отправила резюме")
    has_applied = any(m in text for m in applied_markers)

    engaged_context = any(
        kw in text
        for kw in (
            "резюме",
            "hh.ru",
            "headhunter",
            "отклик",
            "рассмотр",
            "приглашаем",
            "слот",
            "собеседован",
            "интересно",
            "актуально",
        )
    )

    status = analysis.funnel_status

    if (
        analysis.vacancy_id
        and analysis.intent
        in (
            "hr_outreach",
            "follow_up",
            "general",
            "unknown",
        )
        and not has_applied
    ):
        return analysis.model_copy(update={"funnel_status": FunnelStatus.SCREENING})

    if (
        engaged_context
        and analysis.intent == "scheduling_request"
        and has_applied
        and funnel_status_rank(status) <= funnel_status_rank(FunnelStatus.SCREENING)
    ):
        return analysis.model_copy(update={"funnel_status": FunnelStatus.APPLIED})

    if (
        engaged_context
        and analysis.intent in ("hr_outreach", "follow_up")
        and has_applied
        and funnel_status_rank(status) < funnel_status_rank(FunnelStatus.APPLIED)
    ):
        return analysis.model_copy(update={"funnel_status": FunnelStatus.APPLIED})

    if not status and analysis.company not in ("", "Неизвестная компания"):
        return analysis.model_copy(update={"funnel_status": FunnelStatus.SCREENING})

    return analysis
