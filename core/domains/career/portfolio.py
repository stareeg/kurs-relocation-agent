"""Портфолио: элементы из резюме / разборов / оффер-переговоров.

Чистые функции (`draft_*`) — без UI и без записи в БД. Persist — через
``repo.insert_portfolio_item``. `record_portfolio_from_*` — подписчики шины (Этап 5.2 редизайна
«Карьеры»): грузят полную запись по событию и сохраняют черновик сразу, без промежуточного
статуса.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from core.domains.career.models import PortfolioItem
from core.domains.career.repo import insert_portfolio_item
from core.domains.profile.model import Experience, ResumeData
from core.kernel.events import InterviewDebriefed, OfferReceived
from core.platform.db.pool import Executor
from core.platform.observability.logging import event

logger = logging.getLogger(__name__)

# Строка с цифрой / % / «x» — кандидат на «результат в цифрах».
_OUTCOME_HINT = re.compile(r"\d|%|\b[xх]\b", re.IGNORECASE)


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if line:
            lines.append(line)
    return lines


def _outcome_from_description(description: str) -> str:
    """Вытащить 1–3 строки с цифрами; иначе первые две содержательные."""
    lines = _clean_lines(description)
    if not lines:
        return ""
    with_nums = [ln for ln in lines if _OUTCOME_HINT.search(ln)]
    picked = with_nums[:3] if with_nums else lines[:2]
    return "\n".join(picked)


def _project_title(exp: Experience) -> str:
    company = (exp.company or "").strip()
    industry = (exp.industry or "").strip()
    if company and industry:
        return f"{company} ({industry})"
    return company or (exp.position or "").strip() or "Проект"


def _experience_source_ref(index: int, exp: Experience) -> str:
    company = re.sub(r"\s+", "_", (exp.company or "").strip())[:40]
    start = (exp.start or "").strip().replace(" ", "")
    return f"resume:exp:{index}:{company}:{start}".rstrip(":")


def draft_portfolio_from_resume(data: ResumeData) -> list[PortfolioItem]:
    """Черновой список элементов портфолио из опыта в ``ResumeData``.

    Один блок experience → один ``PortfolioItem``. Пустые (нет компании и роли) пропускаем.
    """
    items: list[PortfolioItem] = []
    for i, exp in enumerate(data.experience or []):
        company = (exp.company or "").strip()
        role = (exp.position or "").strip()
        if not company and not role:
            continue
        items.append(
            PortfolioItem(
                project=_project_title(exp),
                role=role,
                outcome=_outcome_from_description(exp.description or ""),
                artifact_url=(exp.company_url or "").strip(),
                source_ref=_experience_source_ref(i, exp),
                notes="",
            )
        )
    return items


def draft_portfolio_from_debrief(
    *,
    vacancy_id: str = "",
    company: str = "",
    strong_answers: Sequence[str] = (),
    summary: str = "",
    debrief_id: int | None = None,
) -> list[PortfolioItem]:
    """Черновик из разбора собеса: сильные ответы + summary как заметка к проекту."""
    company = (company or "").strip()
    vacancy_id = (vacancy_id or "").strip()
    project = company or (f"Собес {vacancy_id}" if vacancy_id else "Разбор собеседования")
    ref = (
        f"debrief:{debrief_id}"
        if debrief_id is not None
        else (f"debrief:{vacancy_id}" if vacancy_id else "debrief")
    )

    items: list[PortfolioItem] = []
    answers = [a.strip() for a in strong_answers if a and str(a).strip()]
    if answers:
        items.append(
            PortfolioItem(
                project=project,
                role="Кандидат",
                outcome="\n".join(answers[:5]),
                source_ref=ref,
                notes=(summary or "").strip(),
            )
        )
    elif (summary or "").strip():
        items.append(
            PortfolioItem(
                project=project,
                role="Кандидат",
                outcome=(summary or "").strip(),
                source_ref=ref,
            )
        )
    return items


def draft_portfolio_from_offer(
    *,
    vacancy_id: str,
    company: str = "",
    position: str = "",
    base_salary: int | None = None,
    base_salary_currency: str = "RUB",
    negotiation_points: Sequence[str] = (),
) -> list[PortfolioItem]:
    """Черновик из оффера / переговоров: вилка + аргументы торга как outcome."""
    vacancy_id = (vacancy_id or "").strip()
    if not vacancy_id and not (company or "").strip():
        return []
    company = (company or "").strip() or vacancy_id
    role = (position or "").strip()
    parts: list[str] = []
    if base_salary is not None and base_salary > 0:
        cur = (base_salary_currency or "RUB").strip() or "RUB"
        parts.append(f"Оффер: {base_salary:,} {cur}/мес".replace(",", " "))
    for point in negotiation_points:
        text = (point or "").strip()
        if text:
            parts.append(text)
    if not parts:
        parts.append("Оффер зафиксирован")
    return [
        PortfolioItem(
            project=f"Оффер · {company}",
            role=role,
            outcome="\n".join(parts[:6]),
            source_ref=f"offer:{vacancy_id or company}",
        )
    ]


async def persist_portfolio_items(
    items: Sequence[PortfolioItem], *, account_id: int, db: Executor | None = None
) -> list[PortfolioItem]:
    """Сохранить пачку черновиков (резюме/разбор собеса/оффер) как элементы портфолио."""
    saved = [await insert_portfolio_item(item, account_id=account_id, db=db) for item in items]
    event(
        logger,
        "ЗАДАЧА",
        "career.portfolio: сохранено %d черновиков",
        len(saved),
        account_id=account_id,
        items_saved=len(saved),
    )
    return saved


async def record_portfolio_from_debrief(
    evt: InterviewDebriefed, *, account_id: int, db: Executor | None = None
) -> list[PortfolioItem]:
    """Разбор с сильными ответами → достижение сразу как обычная запись (Этап 5.2 редизайна
    «Карьеры», решение владельца п.3 — без промежуточного статуса «черновик»). Идемпотентно
    по `source_ref` (0152/Этап 1) — повторная доставка события не дублирует карточку."""
    from core.domains.preparation.debrief import get_debrief, load_debrief_history

    record = None
    if evt.debrief_id is not None:
        record = await get_debrief(evt.debrief_id, account_id=account_id, db=db)
    if record is None:
        vacancy_id = str(evt.vacancy_id or "").strip()
        if vacancy_id:
            history = await load_debrief_history(vacancy_id, limit=1, account_id=account_id, db=db)
            record = history[0] if history else None
    if record is None:
        return []

    analysis = record.analysis or {}
    strong_answers = [
        str(a).strip() for a in (analysis.get("strong_answers") or []) if str(a).strip()
    ]
    if not strong_answers:
        return []

    drafts = draft_portfolio_from_debrief(
        vacancy_id=record.vacancy_id,
        strong_answers=strong_answers,
        summary=record.summary or str(analysis.get("summary") or ""),
        debrief_id=record.id,
    )
    if not drafts:
        return []
    try:
        return await persist_portfolio_items(drafts, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — портфолио не валит обработку разбора
        logger.warning("career_portfolio: не записан из debrief_id=%s: %s", record.id, exc)
        return []


async def record_portfolio_from_offer(
    evt: OfferReceived, *, account_id: int, db: Executor | None = None
) -> list[PortfolioItem]:
    """Оффер зафиксирован → достижение сразу как обычная запись (Этап 5.2, то же решение
    владельца — без «черновика»). Вилка/аргументы торга — с самого оффера (`offers.load_offer`),
    событие несёт только `company`. Идемпотентно по `source_ref` (0152/Этап 1)."""
    from core.domains.offers.store import load_offer

    vacancy_id = str(evt.vacancy_id or evt.offer_id or "").strip()
    offer = await load_offer(vacancy_id, account_id=account_id, db=db) if vacancy_id else None
    if offer is None:
        return []

    negotiation = offer.negotiation or {}
    negotiation_points = [
        str(arg.get("wording") or "").strip()
        for arg in negotiation.get("arguments", [])
        if isinstance(arg, dict) and str(arg.get("wording") or "").strip()
    ]
    drafts = draft_portfolio_from_offer(
        vacancy_id=offer.vacancy_id,
        company=offer.company or evt.company,
        position=offer.position,
        base_salary=offer.base_salary,
        base_salary_currency=offer.base_salary_currency,
        negotiation_points=negotiation_points,
    )
    if not drafts:
        return []
    try:
        return await persist_portfolio_items(drafts, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — портфолио не валит обработку оффера
        logger.warning("career_portfolio: не записан из offer vacancy_id=%s: %s", vacancy_id, exc)
        return []


__all__ = [
    "draft_portfolio_from_debrief",
    "draft_portfolio_from_offer",
    "draft_portfolio_from_resume",
    "persist_portfolio_items",
    "record_portfolio_from_debrief",
    "record_portfolio_from_offer",
]
