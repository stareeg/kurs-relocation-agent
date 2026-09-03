"""«Выученные предпочтения» — динамический хвост system-промпта скоринга (Этап 7 §7.4, D12).

`score_vacancy(..., preferences=...)` был полностью проведён до `_score_with_llm`'s
`dynamic_tail` (Role=2, 3.4), но ни один продовый вызывающий его не передавал — путь был мёртвой
обвязкой (plans/scoring_precision_2026_08_17.md §1.9/§9). Этот модуль его наполняет: два
детерминированных, БЕЗ LLM среза по уже накопленным решениям владельца —

- канонические причины ручного пропуска (`skip_reasons.canonical_skip_reason`), самые частые;
- ниши вакансий (`role_content_match.matched_niche`, уже канонизированы `niche_canon.py` при
  записи скора), на которые владелец реально откликнулся (`has_responded_status`).

Ниже минимального объёма выборки — пустая строка (`""`): свежий/маленький аккаунт получает
промпт как раньше, без шума на одной-двух точках. Только чтение Postgres, ни одного LLM-вызова —
не нарушает бюджет §1.13 («новых последовательных LLM-вызовов в POST /score не добавляем»).
"""

from __future__ import annotations

import logging
from collections import Counter

from core.domains.opportunities.jobs import Job, list_jobs
from core.domains.opportunities.skip_reasons import canonical_skip_reason
from core.kernel.schemas.funnel import has_responded_status
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# Тот же приём, что у axis_alignment.py: `list_jobs` требует limit, лимит завышен намеренно —
# для масштаба одного аккаунта (CLAUDE.md) это эффективно «без лимита».
_REPORT_JOB_LIMIT = 20_000

_MIN_SKIP_SAMPLES = 5
_MIN_RESPONDED_SAMPLES = 3
_TOP_SKIP_REASONS = 3
_TOP_NICHES = 5


def _top_skip_reasons(skip_reasons_raw: list[str]) -> list[tuple[str, int]]:
    if len(skip_reasons_raw) < _MIN_SKIP_SAMPLES:
        return []
    counter: Counter[str] = Counter(canonical_skip_reason(r) for r in skip_reasons_raw)
    return counter.most_common(_TOP_SKIP_REASONS)


def _top_responded_niches(jobs: list[Job]) -> list[str]:
    responded = [j for j in jobs if has_responded_status(j.status)]
    if len(responded) < _MIN_RESPONDED_SAMPLES:
        return []
    counter: Counter[str] = Counter()
    for job in responded:
        niches = (job.score or {}).get("role_content_match", {}).get("matched_niche") or []
        for niche in niches:
            name = str(niche).strip()
            if name:
                counter[name] += 1
    return [name for name, _count in counter.most_common(_TOP_NICHES)]


def build_preferences_block(skip_reasons_raw: list[str], jobs: list[Job]) -> str:
    """Чистая сборка текста — без DB, юнит-тестируется отдельно от `learned_preferences_block`."""
    top_reasons = _top_skip_reasons(skip_reasons_raw)
    top_niches = _top_responded_niches(jobs)
    if not top_reasons and not top_niches:
        return ""

    lines = [
        "ВЫУЧЕННЫЕ ПРЕДПОЧТЕНИЯ (по фактическим решениям владельца, не с его слов — "
        "используй как мягкий контекст в pros/cons/red_flags, не как жёсткое правило "
        "и не как повод менять recommendation в одиночку):"
    ]
    if top_niches:
        lines.append(
            f"- Ниши вакансий, на которые владелец чаще откликается: {', '.join(top_niches)}."
        )
    if top_reasons:
        formatted = ", ".join(f"{reason} ({count})" for reason, count in top_reasons)
        lines.append(f"- Причины, по которым он чаще всего пропускает вакансии: {formatted}.")
    return "\n".join(lines)


async def learned_preferences_block(account_id: int, *, db: Executor | None = None) -> str:
    """Best-effort: каллер (`persist.py::score_and_persist`) обязан пережить любую ошибку отсюда —
    сама вилка предпочтений не должна стоить скоринга."""
    executor = db or get_pool()
    jobs = await list_jobs(limit=_REPORT_JOB_LIMIT, account_id=account_id, db=executor)
    skip_rows = await executor.fetch(
        "select skip_reason from skipped_vacancies where account_id = $1", account_id
    )
    return build_preferences_block([r["skip_reason"] for r in skip_rows if r["skip_reason"]], jobs)


async def learned_preferences_block_safe(account_id: int, *, db: Executor | None = None) -> str:
    """Best-effort обёртка (как `assess_remote_feasibility_safe`): любая ошибка → "" вместо
    падения — вилка предпочтений не должна стоить самого скоринга."""
    try:
        return await learned_preferences_block(account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — DB/сеть; блок предпочтений не критичен
        logger.warning("Выученные предпочтения не посчитаны: %s", exc)
        return ""


__all__ = [
    "build_preferences_block",
    "learned_preferences_block",
    "learned_preferences_block_safe",
]
