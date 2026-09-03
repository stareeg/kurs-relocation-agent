"""Канон причин ручного пропуска вакансии.

Единый источник правды для бэкенда. Эталонный JSON для синка UI:
``core/domains/opportunities/skip_reasons.json``
(``python -m core.domains.opportunities.dump_skip_reasons``).
Тесты frontend/extension сверяют свои литералы с этим снапшотом.

Потребители:
- frontend/src/features/jobs/reject-reasons.ts
- extension/src/skip-reasons.ts
- bot_app/services/vacancy_card.py (импорт из этого модуля)

Канон был переименован (2026-08-10):
- «Риск выгорания» → «Не та роль (IC vs рук)» — причина связана с балансом
  IC/менеджерских функций, а не с выгоранием; старое название было неинтуитивно.
- «Сомнительная компания» → «Избегать компанию» — вынесена как отдельная
  статичная кнопка, но остаётся в каноне для совместимости с веб-дровером и
  бэктфилом исторических причин. Legacy-строки «Сомнительная компания» и
  «Риск выгорания» матчатся в новый канон.
"""

from __future__ import annotations

import re
from typing import Literal

# Именованный Literal — для Pydantic/pyright (нельзя Literal[SELF_SKIP_REASONS] с переменной).
CanonicalSkipReason = Literal[
    "Низкий грейд",
    "Низкая зарплата",
    "Не тот стек/домен",
    "Не тот формат",
    "Не та роль (IC vs рук)",
    "Избегать компанию",
]

SELF_SKIP_REASONS: tuple[CanonicalSkipReason, ...] = (
    "Низкий грейд",
    "Низкая зарплата",
    "Не тот стек/домен",
    "Не тот формат",
    "Не та роль (IC vs рук)",
    "Избегать компанию",
)

SKIP_REASON_GRID_KEYS: dict[str, str] = {
    "Низкий грейд": "skip_low_grade",
    "Низкая зарплата": "skip_low_salary",
    "Не тот стек/домен": "skip_wrong_stack_domain",
    "Не тот формат": "skip_wrong_format",
    "Не та роль (IC vs рук)": "skip_role_kind",
    "Избегать компанию": "skip_bad_company",
}

_CANONICAL_SET = frozenset(SELF_SKIP_REASONS)

# Точные legacy-строки: чипы UI до JS-22.0, промежуточные варианты и раздельные
# «Не тот стек» / «Не тот домен» до слияния в один канон (EXT-P1).
# Включает старые названия причин до переименования 2026-08-10:
# «Риск выгорания» → «Не та роль (IC vs рук)»,
# «Сомнительная компания» → «Избегать компанию».
_LEGACY_EXACT: dict[str, str] = {
    "Зарплата ниже целевой": "Низкая зарплата",
    "Низкая зарплата": "Низкая зарплата",
    "Грейд ниже Senior+": "Низкий грейд",
    "Грейд не совпадает": "Низкий грейд",
    "Не полная удалёнка": "Не тот формат",
    "Офис / нет удалёнки": "Не тот формат",
    # Старое название причины пропуска (до переименования 2026-08-10).
    "Риск выгорания": "Не та роль (IC vs рук)",
    # Старое название причины пропуска (до переименования 2026-08-10).
    "Сомнительная компания": "Избегать компанию",
    "Другое": "Избегать компанию",
    "Не интересно": "Избегать компанию",
    "без причины": "Избегать компанию",
    "Не тот стек": "Не тот стек/домен",
    "Не тот домен": "Не тот стек/домен",
    "Стек/домен далёкий": "Не тот стек/домен",
    "Не тот стек / домен": "Не тот стек/домен",
}

# Строки, которые пользователь мог выбрать вручную (чип) — отличие от автоматических скипов.
_MANUAL_CHIP_STRINGS: frozenset[str] = _CANONICAL_SET | frozenset(_LEGACY_EXACT)

_RE_STACK_DOMAIN = re.compile(
    r"стек|stack|домен|domain|технолог|rag|agent|llm|nlp|\bbi\b|\bcv\b|классическ.*ml|"
    r"data engineer(?!.*llm)|аналитик|wrong_domain|generic_backend",
    re.I,
)

# Ключевые слова для «Не та роль (IC vs рук)» — баланс IC/менеджерских функций.
# Включает legacy-маркеры выгорания/нагрузки/токсичности (исторически эта причина
# их собирала), плюс новые маркеры роли: управление/руководство/менеджер/IC/people.
_RE_ROLE_KIND = re.compile(
    r"выгор|burnout|переработ|нагрузк|токсич|"
    r"управлен|менеджер|руковод|people\s*manager|"
    r"\bic\b|individual\s*contributor|хендс-?он|hands-?on|"
    r"доля\s*управлен|роль\s*менеджер|руководящ",
    re.I,
)


def _norm(raw: str) -> str:
    return raw.lower().replace("ё", "е").strip()


def canonical_skip_reason(raw: str | None) -> str:
    """Свести произвольную причину пропуска к одной из SELF_SKIP_REASONS."""
    if raw is None or not str(raw).strip():
        return "Избегать компанию"

    stripped = str(raw).strip()
    if stripped in _CANONICAL_SET:
        return stripped

    if stripped in _LEGACY_EXACT:
        return _LEGACY_EXACT[stripped]

    s = _norm(stripped)

    if "recommendation=skip" in s or s == "skip":
        return "Избегать компанию"

    if re.search(r"зарплат|вилк|деньг|оплат|ниже\s*цел|мало\s*плат|low\s*salar", s):
        return "Низкая зарплата"
    if _RE_ROLE_KIND.search(s):
        return "Не та роль (IC vs рук)"
    if re.search(r"удален|офис|гибрид|формат|на\s*месте|on-?site|remote|релок", s):
        return "Не тот формат"
    if re.search(r"грейд|grade|junior|middle|уровень|позиц|не\s*тот\s*грейд", s):
        return "Низкий грейд"
    if _RE_STACK_DOMAIN.search(s):
        return "Не тот стек/домен"

    if re.search(r"не\s*интерес|аутстафф|аутсорс|сомнительн|избегать|ненадеж|ненадёж", s):
        return "Избегать компанию"

    return "Избегать компанию"


def needs_llm_backfill(raw: str | None) -> bool:
    """True если строка требует LLM-классификации: не канон и не точный legacy-алиас.

    Использует `scripts/backfill/backfill_skip_reasons.py` — там, где точное совпадение уже решает
    вопрос, LLM звать незачем; спорные/произвольные строки (в т.ч. смешанные причины, которые
    regex-каскад в `canonical_skip_reason` матчит по первому совпадению) — как раз то, что чинит
    backfill.
    """
    stripped = (raw or "").strip()
    return bool(stripped) and stripped not in _CANONICAL_SET and stripped not in _LEGACY_EXACT


def is_manual_skip_reason(reason: str | None) -> bool:
    """True если причина — ручной выбор чипа (не авто-вердикт LLM)."""
    return (reason or "").strip() in _MANUAL_CHIP_STRINGS


def aggregate_skip_reason_counts(
    rows: list[tuple[str, int]],
    *,
    include_zero: bool = False,
) -> list[tuple[str, int]]:
    """Сгруппировать сырые (reason, count) по канону в порядке SELF_SKIP_REASONS."""
    totals = {label: 0 for label in SELF_SKIP_REASONS}
    for reason, count in rows:
        totals[canonical_skip_reason(reason)] += int(count)
    if include_zero:
        return [(label, totals[label]) for label in SELF_SKIP_REASONS]
    return [(label, totals[label]) for label in SELF_SKIP_REASONS if totals[label] > 0]


def format_skip_breakdown(counts: list[tuple[str, int]]) -> str:
    """Строка для LLM: весь канон причин, нули явно."""
    by_label = {label: 0 for label in SELF_SKIP_REASONS}
    for label, count in counts:
        by_label[canonical_skip_reason(label)] += int(count)
    return ", ".join(f"{label} {by_label[label]}" for label in SELF_SKIP_REASONS)


__all__ = [
    "SELF_SKIP_REASONS",
    "SKIP_REASON_GRID_KEYS",
    "aggregate_skip_reason_counts",
    "canonical_skip_reason",
    "format_skip_breakdown",
    "is_manual_skip_reason",
    "needs_llm_backfill",
]
