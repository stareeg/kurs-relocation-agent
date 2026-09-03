"""Канон написаний ниш (`role_content_match.matched_niche`).

Аналог `skill_canon.py`, но для многословных фраз ниш, а не отдельных названий технологий:
модель называет одну и ту же нишу по-разному между вызовами («mlops/llmops», «mlops и
llmops», «llm-инфраструктура» — 189 упоминаний на проде под 5 написаниями, см.
plans/scoring_precision_2026_08_17.md §1.7/§4.2). Без схлопывания аналитика по нишам не
считается.

Применяется постпроцессингом (`scorer._postprocess`), не в промпте — модель не обязана
знать наш канон. Словарь — в `prompts/opportunities/niche_canon.yaml` (не Python), как и
`weights_spec.yaml`: правится без деплоя кода. Короткий словарь известных синонимов —
неизвестное написание (в т.ч. ниша кандидата другой специальности) остаётся как есть.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = ["canonical_niche_name", "canonicalize_niches"]

# Относительный путь (не Path(__file__)) — тот же приём, что у prompts в llm.py/prompt.py:
# процесс всегда запускается из корня репо (CLAUDE.md), путь читаем от CWD.
NICHE_CANON_PATH = "prompts/opportunities/niche_canon.yaml"


def _fold_key(name: str) -> str:
    """Ключ сравнения: casefold + ё→е + схлопнутые пробелы (как `skill_canon._fold_key`)."""
    s = name.casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    path = Path(NICHE_CANON_PATH)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("aliases") or {}
    return {_fold_key(str(k)): str(v) for k, v in raw.items()}


def canonical_niche_name(niche: str) -> str:
    """Известный алиас → канон; неизвестное написание — как есть (только trim)."""
    alias = _aliases().get(_fold_key(niche))
    return alias if alias else niche.strip()


def canonicalize_niches(niches: list[str]) -> list[str]:
    """Список ниш → канонизированный, без дублей (порядок первого появления сохраняется).

    Дедуп нужен: две ниши, разошедшиеся только написанием («RAG» и «rag и graphrag»),
    после канона схлопываются в одну — агрегат снимка не должен считать их дважды.
    """
    seen: dict[str, str] = {}
    order: list[str] = []
    for raw in niches:
        name = (raw or "").strip()
        if not name:
            continue
        canon = canonical_niche_name(name)
        key = canon.casefold()
        if key not in seen:
            seen[key] = canon
            order.append(key)
    return [seen[k] for k in order]
