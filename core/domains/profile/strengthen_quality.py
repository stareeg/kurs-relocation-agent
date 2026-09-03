"""Качество выхода strengthen/ATS: анти-slop, анти-косметика, директива усиления."""

from __future__ import annotations

import re

from core.domains.profile.model import ResumeData
from core.domains.profile.score_criteria import format_search_axes_block
from core.kernel.text.style_lint import StyleIssue, lint

# Jaccard токенов: выше порога — почти пересказ (ловушка «1% правок»).
COSMETIC_SIMILARITY_THRESHOLD = 0.82
# Минимальный прирост длины относительно исходника (refine).
MIN_LENGTH_GROWTH_RATIO = 0.92

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9+-]+", re.UNICODE)

_STRENGTHEN_LINT_CHECKS = ("officialese", "cliches", "anglicisms", "punctuation")


def _token_set(text: str) -> set[str]:
    return {t.casefold() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def token_jaccard_similarity(a: str, b: str) -> float:
    """Сходство 0..1 по множеству слов."""
    sa, sb = _token_set(a), _token_set(b)
    union = sa | sb
    if not union:
        return 1.0 if not (a or b) else 0.0
    return len(sa & sb) / len(union)


def is_substantive_enhancement(original: str, proposed: str) -> bool:
    """False, если proposed — косметический пересказ или урезание без усиления."""
    orig = (original or "").strip()
    prop = (proposed or "").strip()
    if not orig:
        return bool(prop)
    if not prop:
        return False
    if token_jaccard_similarity(orig, prop) >= COSMETIC_SIMILARITY_THRESHOLD:
        return False
    return len(prop) >= len(orig) * MIN_LENGTH_GROWTH_RATIO


def lint_strengthen_text(text: str, keep_terms: list[str] | None = None) -> list[StyleIssue]:
    """Анти-slop для блока резюме; технологии из keep_terms разрешены."""
    allowed = set(keep_terms or [])
    return lint(text, allowed_terms=allowed, checks=_STRENGTHEN_LINT_CHECKS)


def format_enhancement_directive(data: ResumeData) -> str:
    """Директива для промпта: усиление под цели слева, не перефразирование."""
    pos = data.position
    sc = data.search_criteria
    lines = [
        "## Цель подгонки под ATS (усиление, не пересказ)",
        "Задача — приукрасить и усилить опыт/достижения под критерии поиска слева:",
        "добавить масштаб, задачи, технологии и результаты, правдоподобные для целевого грейда.",
        "Кандидат сам уберёт лишнее; лучше чуть смелее, чем косметика на 1%.",
        "Запрещено: переставить те же слова, заменить синонимами без нового содержания.",
    ]
    if pos.title:
        lines.append(f"Желаемая должность: {pos.title.strip()}.")
    if pos.grade:
        grades = ", ".join(g for g in pos.grade if g.strip())
        lines.append(
            f"Целевой грейд: {grades}. Если буллеты читаются уровнем ниже — "
            "подтяни масштаб (команда, система, влияние, метрики). "
            "Компании и должности из резюме не меняй; задачи и достижения усили смело."
        )
    if sc.role_kind:
        lines.append(f"Тип роли: {sc.role_kind.strip()}.")
    if sc.niches:
        lines.append(
            "Приоритеты: "
            + ", ".join(sc.niches[:6])
            + " — добавь следы в буллеты и «Обо мне», где правдоподобно."
        )
    if sc.market_segment:
        lines.append(f"Рынок/отрасль: {sc.market_segment.strip()}.")
    lines.append("")
    lines.append("## Критерии поиска (левая панель)")
    lines.append(format_search_axes_block(data))
    return "\n".join(lines)


def build_cosmetic_repair_user(
    *,
    kind: str,
    original: str,
    proposed: str,
    role_title: str,
    enhancement_block: str,
) -> str:
    """User-промпт для одного repair-вызова, когда LLM почти не изменила текст."""
    role = f"Роль: {role_title}." if role_title else ""
    return f"""{role}

{enhancement_block}

Блок «{kind}». Исходник и черновик почти совпали — это косметический пересказ.
Нужно СУЩЕСТВЕННОЕ усиление: новые буллеты или развёрнутые формулировки с масштабом,
технологиями, результатами под целевой грейд. Якоря (компания, роль) сохрани.

## Исходный текст

{original}

## Слишком похожий черновик (переделать)

{proposed}

Верни только усиленный текст блока, формат `- …` построчно."""


__all__ = [
    "COSMETIC_SIMILARITY_THRESHOLD",
    "build_cosmetic_repair_user",
    "format_enhancement_directive",
    "is_substantive_enhancement",
    "lint_strengthen_text",
    "token_jaccard_similarity",
]
