"""Сводка батча пересланных вакансий: счётчики, топ-строки, фильтр карточек.

Чистые функции без TG/PG — удобно тестировать. Пороги карточек:
только ``apply`` / ``strong_apply``.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot_app.services.menu_manager import BatchStats
from bot_app.services.vacancy_card import REC_LABELS
from core.domains.opportunities.models import ScoreResult

CARD_RECOMMENDATIONS = frozenset({"strong_apply", "apply"})

_TOP_N_DEFAULT = 5


@dataclass(frozen=True)
class BatchScoreRow:
    """Одна успешно оценённая вакансия в батче (для сводки)."""

    overall_score: int
    recommendation: str
    company: str
    title: str
    vacancy_id: str = ""


def row_from_score(
    score: ScoreResult,
    *,
    company: str = "",
    title: str = "",
    vacancy_id: str = "",
) -> BatchScoreRow:
    """BatchScoreRow из доменного ScoreResult (+ поля Job для подписи)."""
    return BatchScoreRow(
        overall_score=int(score.overall_score),
        recommendation=str(score.recommendation),
        company=(company or "").strip(),
        title=(title or "").strip(),
        vacancy_id=vacancy_id or "",
    )


def is_card_worthy(recommendation: str) -> bool:
    """Карточку в чат шлём только для apply / strong_apply."""
    return recommendation in CARD_RECOMMENDATIONS


def count_batch_stats(rows: list[BatchScoreRow], *, errors: int = 0) -> BatchStats:
    """Счётчики для меню after_score. Ошибки скоринга кладём в «мимо»."""
    strong = sum(1 for r in rows if r.recommendation == "strong_apply")
    apply = sum(1 for r in rows if r.recommendation == "apply")
    skip = sum(1 for r in rows if r.recommendation not in CARD_RECOMMENDATIONS) + max(0, errors)
    return BatchStats(
        total=len(rows) + max(0, errors),
        strong=strong,
        apply=apply,
        skip=skip,
    )


def format_batch_summary(
    rows: list[BatchScoreRow],
    *,
    errors: int = 0,
    top_n: int = _TOP_N_DEFAULT,
) -> str:
    """Текст сводки: «N вакансий: X сильных / Y подать / Z мимо» + топ по скору."""
    stats = count_batch_stats(rows, errors=errors)
    lines = [
        (
            f"{stats.total} вакансий: {stats.strong} сильных / "
            f"{stats.apply} подать / {stats.skip} мимо"
        )
    ]
    if errors > 0:
        lines.append(f"Ошибок оценки: {errors}")

    ranked = sorted(rows, key=lambda r: (-r.overall_score, r.recommendation != "strong_apply"))
    if ranked:
        lines.append("")
        for row in ranked[: max(1, top_n)]:
            label = REC_LABELS.get(row.recommendation, row.recommendation)
            company = row.company or "—"
            title = row.title or "—"
            lines.append(f"• {row.overall_score} {label} — {company} — {title}")
    elif errors == 0:
        lines.append("")
        lines.append("Нечего показать.")

    return "\n".join(lines)


def progress_text(done: int, total: int) -> str:
    """Текст progress-сообщения (без эмодзи)."""
    return f"Читаю {total} постов… {done}/{total}"
