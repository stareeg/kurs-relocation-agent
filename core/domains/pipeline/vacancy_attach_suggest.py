"""FR2-87: предложение привязать вставленный HR-дамп к уже известной вакансии.

hh/getmatch-ссылка или название компании в тексте → существующий `jobs.vacancy_id`.
Матч по компании идёт через `find_jobs_by_company` + `pick_company_match_candidates`
(канон FR2-39 / FR3-72). LLM не зовём: достаточно ссылок и детерминированного поиска
по алиасам/именам из воронки владельца.

UI: ровно 1 кандидат → чип «Привязать к …?»; ≥2 → пикер (не silent pick);
решение за владельцем (feedback_llm_advice_not_user_decision).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.domains.opportunities.companies.normalize import (
    COMPANY_ALIASES,
    normalize_company_deterministic,
)
from core.domains.opportunities.jobs import (
    Job,
    extract_getmatch_numeric_id_from_text,
    find_jobs_by_company,
    get_job_by_vacancy_id,
    pick_company_match_candidates,
)
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)


class VacancyAttachSuggestion(BaseModel):
    """Кандидат на привязку дампа к вакансии из воронки."""

    vacancy_id: str
    company: str = ""
    title: str | None = None
    match_via: str = Field(description="url | company")
    label: str = ""
    # FR3-73: чтобы две роли одной компании не сливались в одну подпись.
    status: str | None = None
    activity_at: datetime | None = None


class VacancyAttachSuggestOutcome(BaseModel):
    """Итог поиска: 0 / 1 / много кандидатов."""

    candidates: list[VacancyAttachSuggestion] = Field(default_factory=list)

    @property
    def suggestion(self) -> VacancyAttachSuggestion | None:
        """Удобство: единственный кандидат, иначе None (не silent pick при коллизии)."""
        if len(self.candidates) == 1:
            return self.candidates[0]
        return None


def _relative_activity(dt: datetime | None, *, now: datetime | None = None) -> str:
    """Короткая относительная дата для подписи чипа."""
    if dt is None:
        return ""
    ref = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    days = (ref.date() - dt.astimezone(UTC).date()).days
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "1 дн назад"
    return f"{days} дн назад"


def _activity_at(job: Job) -> datetime | None:
    return job.updated_at or job.scored_at


def _label(
    company: str | None,
    title: str | None,
    vacancy_id: str,
    *,
    status: str | None = None,
    activity_at: datetime | None = None,
) -> str:
    parts = [p for p in ((company or "").strip(), (title or "").strip()) if p]
    base = " · ".join(parts) if parts else f"Вакансия {vacancy_id}"
    meta: list[str] = []
    st = (status or "").strip()
    if st:
        meta.append(st)
    rel = _relative_activity(activity_at)
    if rel:
        meta.append(rel)
    if meta:
        return f"{base} · {' · '.join(meta)}"
    return base


def _suggestion_from_job(job: Job, *, match_via: str) -> VacancyAttachSuggestion:
    vid = (job.vacancy_id or "").strip()
    if not vid:
        raise ValueError("job without vacancy_id")
    activity = _activity_at(job)
    return VacancyAttachSuggestion(
        vacancy_id=vid,
        company=job.company or "",
        title=job.title,
        match_via=match_via,
        status=job.status,
        activity_at=activity,
        label=_label(
            job.company,
            job.title,
            vid,
            status=job.status,
            activity_at=activity,
        ),
    )


def _guess_company_names_in_text(text: str) -> list[str]:
    """Детерминированные кандидаты компании из дампа: алиасы словаря + каноны."""
    raw = (text or "").strip()
    if not raw:
        return []
    folded = raw.casefold().replace("ё", "е")
    tokens = re.findall(r"[a-z0-9а-я-]+", folded)
    found: list[str] = []
    seen: set[str] = set()

    # Длинные алиасы раньше коротких («тинькофф банк» до «тбанк»).
    aliases = sorted(COMPANY_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True)
    for alias, canon in aliases:
        if not alias or canon in seen:
            continue
        # Точное слово или основа (≥4): «сбер»→«сбера», «яндекс»→«яндекса».
        hit = False
        if " " in alias:
            hit = alias in folded
        else:
            for tok in tokens:
                if tok == alias or (len(alias) >= 4 and tok.startswith(alias)):
                    hit = True
                    break
        if hit:
            seen.add(canon)
            found.append(canon)

    # Явный канон в тексте («Сбербанк», «Яндекс») без алиаса.
    for canon in sorted(set(COMPANY_ALIASES.values()), key=len, reverse=True):
        if canon in seen:
            continue
        key = canon.casefold().replace("ё", "е")
        if key and any(tok == key or (len(key) >= 4 and tok.startswith(key)) for tok in tokens):
            seen.add(canon)
            found.append(canon)

    return found


async def suggest_vacancy_attach(
    text: str,
    *,
    company: str = "",
    vacancy_url: str = "",
    account_id: int,
    db: Executor | None = None,
) -> VacancyAttachSuggestOutcome:
    """Найти существующие вакансии для привязки дампа. Пустой candidates — нечего предлагать."""
    combined = "\n".join(p for p in (vacancy_url.strip(), text.strip()) if p)
    if len(combined) < 8 and not company.strip():
        return VacancyAttachSuggestOutcome()
    db = db or get_pool()

    from core.domains.pipeline.vacancy_links import extract_primary_vacancy_id

    # 1) hh / getmatch-ссылка → vacancy_id, если вакансия уже в воронке (всегда один).
    hh_id = extract_primary_vacancy_id(combined, vacancy_url.strip())
    gm_num = extract_getmatch_numeric_id_from_text(combined)
    for vid, via in (
        (hh_id, "url"),
        (f"gm_{gm_num}" if gm_num else "", "url"),
    ):
        if not vid:
            continue
        job = await get_job_by_vacancy_id(vid, account_id=account_id, db=db)
        if job is None:
            continue
        return VacancyAttachSuggestOutcome(candidates=[_suggestion_from_job(job, match_via=via)])

    # 2) Компания: поле черновика → имена из дампа → find_jobs_by_company + ярус.
    candidates: list[str] = []
    hint = (company or "").strip()
    if hint:
        candidates.append(hint)
        canon = normalize_company_deterministic(hint)
        if canon and canon != hint:
            candidates.append(canon)
    for name in _guess_company_names_in_text(combined):
        if name not in candidates:
            candidates.append(name)

    for name in candidates:
        jobs = await find_jobs_by_company(name, account_id=account_id, db=db)
        top = pick_company_match_candidates(jobs)
        if not top:
            continue
        logger.info(
            "vacancy_attach_suggest: company=%r → %d кандидат(ов) %s",
            name,
            len(top),
            [j.vacancy_id for j in top],
        )
        return VacancyAttachSuggestOutcome(
            candidates=[_suggestion_from_job(j, match_via="company") for j in top]
        )

    return VacancyAttachSuggestOutcome()


__all__ = [
    "VacancyAttachSuggestion",
    "VacancyAttachSuggestOutcome",
    "suggest_vacancy_attach",
]
