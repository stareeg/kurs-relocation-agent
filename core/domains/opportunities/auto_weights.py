"""Автоматический расчёт весов скоринга по резюме (F-?).

Ручной блок «Приоритеты оценки» в «Резюме» удалён: веса больше не вводятся юзером, а
выводятся из того, что КАНДИДАТ уже указал в резюме. Логика детерминированная (без LLM):
каждый из настраиваемых критериев получает долю из оставшегося пула (после фиксированного
`salary`) пропорционально тому, насколько сигнал по нему явно задан в резюме.

Принцип простой: если кандидат явно указал ось (формат работы, грейды, ниши/стек, списки
компаний) — значит она ему важна, и ей достаётся больше веса. Пустая ось = кандидату не
так важно → вес ближе к минимальному. Сумма настраиваемых весов всегда `tunable_share`.

`management` — тоже настраиваемый, но не по сигналу резюме, а по `role_kind` (Этап 3,
plans/scoring_precision_2026_08_17.md §5): полный вес только когда кандидат явно выбрал
сторону (hands_on/management), иначе минимальная база.

`role_content` (Этап 4 §4.1) — тоже вне пропорционального пула наравне с остальными тремя:
единственная ось с измеренной предиктивной силой на решениях владельца (82 против 47 у
откликнулся/не откликнулся, plans/scoring_precision_2026_08_17.md §1.6), поэтому получает
базу выше их потолка и растёт с насыщенностью категорий/ниш, а не наравне с company/grade.

Фиксированный вес (`salary`) совпадает с `score_breakdown` — его формула скоринга не
переопределяет.
"""

from __future__ import annotations

from typing import Any

from core.domains.opportunities.score_breakdown import (
    DEFAULT_WEIGHTS,
    MANAGEMENT_WEIGHT,
    SALARY_WEIGHT,
    SECOND_JOB_WEIGHTS,
)
from core.kernel.schemas.track import DEFAULT_TRACK, SearchTrack

# Пул, который распределяем между настраиваемыми критериями (только salary фиксирован).
# `management` — тоже настраиваемый (Этап 3, plans/scoring_precision_2026_08_17.md): для mixed/
# unknown шкала «Управление» почти симметрична (score_breakdown._MANAGEMENT_FRACTION_BY_ROLE),
# то есть ось несёт мало информации, и её база сжимается в пользу остальных критериев.
TUNABLE_KEYS: tuple[str, ...] = (
    "work_format",
    "grade_match",
    "role_content",
    "company",
    "management",
)

# Ключи, чей вес выводится пропорционально из сигнала резюме (насыщенность списков/полей).
# `management` в этот пул не входит — его база задаёт role_kind (см. _MANAGEMENT_BASE_BY_ROLE).
# `role_content` тоже не входит — его база задаёт _ROLE_CONTENT_BASE/_ROLE_CONTENT_SIGNAL_SPAN
# (Этап 4 §4.1): остальные три делят то, что осталось ПОСЛЕ него, а не наравне с ним.
_SIGNAL_TUNABLE_KEYS: tuple[str, ...] = ("work_format", "grade_match", "role_content", "company")
_OTHER_SIGNAL_KEYS: tuple[str, ...] = ("work_format", "grade_match", "company")

# База «Управления» по role_kind кандидата: ось информативна только когда кандидат внятно
# выбрал сторону (hands_on/management) — тогда её полный вес честен. Для mixed/unknown 78%
# вакансий на проде получали одно и то же число (§1.4 плана) — минимальная база вместо
# фиксированных 15, освободившиеся баллы уходят в остальные критерии этого же пула.
_MANAGEMENT_BASE_BY_ROLE: dict[str, int] = {
    "hands_on": MANAGEMENT_WEIGHT,
    "management": MANAGEMENT_WEIGHT,
    "mixed": 6,
    "unknown": 6,
}

# База «Содержания роли» + рост с насыщенностью категорий/ниш резюме (Этап 4 §4.1: ориентир
# 25-30 из 100, «должен стать самой тяжёлой осью» — 22 уже выше salary/work_format=20 даже
# при пустых категориях/нишах, 30 — потолок при полном сигнале). Диапазон, не фикс: ось всё
# ещё чувствительна к тому, насколько кандидат описал свой стек/нишу, просто больше не наравне
# с company/grade — измеренный разрыв (§1.6 плана) на порядок больше их.
_ROLE_CONTENT_BASE = 22
_ROLE_CONTENT_SIGNAL_SPAN = 8


def _strip(items: Any | None) -> list[str]:
    if not items:
        return []
    return [str(s).strip() for s in items if s and str(s).strip()]


def _signal_strength(*groups: list[str]) -> float:
    """0..1 — насколько ось «задана» прямыми сигналами резюме (сумма насыщенностей).

    Денаминатор 2 — исходная, ещё Этапа 4 калибровка `role_signal` (насыщенность
    категорий/ниш → база `role_content`, `_ROLE_CONTENT_BASE`/`_ROLE_CONTENT_SIGNAL_SPAN` ниже):
    та ось уже тестами закреплена как «самая тяжёлая на заполненном резюме», трогать её кривую
    роста ради несвязанной правки Этапа 5.4 (см. `_pool_signal_strength`) не стоит — только эта
    функция остаётся на старом пороге, специально для `role_signal`.
    """
    total = 0.0
    for group in groups:
        n = len(_strip(group))
        if n == 0:
            continue
        total += min(1.0, n / 2.0)
    return min(1.0, total)


# Этап 5 §5.4 (D7/§1.5): на 2 элементах `_signal_strength` уже давала полный сигнал всем трём
# осям пула сразу — при заполненном резюме work_format/grade_match/company стабильно получали
# одинаковый вес (17/16/16 на проде — «ось заполнена» вырождалось в «веса равномерны», ровно
# наоборот заявленной цели). Порог для ЭТИХ осей (не для `role_signal` — см. выше) поднят:
# типичные 1-3 пункта (грейды, компании) больше не насыщают ось мгновенно.
_POOL_SIGNAL_ITEMS_FOR_FULL_STRENGTH = 5


def _pool_signal_strength(*groups: list[str]) -> float:
    """0..1 — та же идея, что `_signal_strength`, но медленнее насыщается (grade_match/company)."""
    total = 0.0
    for group in groups:
        n = len(_strip(group))
        if n == 0:
            continue
        total += min(1.0, n / _POOL_SIGNAL_ITEMS_FOR_FULL_STRENGTH)
    return min(1.0, total)


# Формат работы — закрытый список максимум из трёх пунктов (офис/гибрид/удалённо), не открытый
# перечень вроде компаний: чем УЖЕ выбор, тем строже кандидат — одна отметка ближе к дилбрейкеру,
# чем «любой из трёх». Старая count-формула считала наоборот: «отметил все три» давала больше
# сигнала, чем «отметил один», хотя отметить всё как раз и значит «формат мне не так важен»
# (Этап 5 §5.4: «не количество, а специфичность»).
_SCHEDULE_SPECIFICITY: dict[int, float] = {0: 0.0, 1: 1.0, 2: 0.55, 3: 0.3}
# Явная отметка «командировки — дилбрейкер» — конкретное стоп-условие кандидата (не про сам
# schedule), поднимает приоритет формата отдельно от того, насколько узко выбран schedule.
_TRAVEL_DEALBREAKER_BONUS = 0.2


def _schedule_specificity(schedule: list[str]) -> float:
    n = min(len(_strip(schedule)), 3)
    return _SCHEDULE_SPECIFICITY[n]


def _second_job_auto_weights(data: Any) -> dict[str, int]:
    """Фиксированная база второго трека + до 5 баллов из company в flexibility/rate.

    Ред-флаги «Учёт часов» и «Онколл» усиливают гибкость; явная валюта USD/EUR — ставку.
    Больше выводить не из чего.
    """
    weights = dict(SECOND_JOB_WEIGHTS)
    sc = getattr(data, "search_criteria", None)
    dealbreakers = set(_strip(getattr(sc, "dealbreakers", None)))
    flex_shift = 0
    if "Учёт часов / микроменеджмент" in dealbreakers:
        flex_shift += 3
    if "Онколл / дежурства 24/7" in dealbreakers:
        flex_shift += 2
    flex_shift = min(5, flex_shift)
    currency = str(getattr(getattr(data, "position", None), "salary_currency", "") or "").upper()
    rate_shift = 5 if currency in {"USD", "EUR"} else 0
    take = min(weights["company"], flex_shift + rate_shift)
    flex_take = min(flex_shift, take)
    rate_take = min(rate_shift, take - flex_take)
    weights["company"] -= flex_take + rate_take
    weights["flexibility"] += flex_take
    weights["rate"] += rate_take
    return weights


def derive_auto_scoring_weights(
    data: Any,
    role_kind: str = "unknown",
    *,
    travel_is_dealbreaker: bool = False,
    track: SearchTrack = DEFAULT_TRACK,
) -> dict[str, int]:
    """ResumeData → веса скоринга (сумма 100), выведенные из сигналов резюме.

    Детерминированная функция от резюме — без LLM и без чтения настроек. Вызывается на
    каждом скоринге (резюме уже загружено), так что правки резюме автоматически меняют веса.
    `role_kind` — из `SearchProfile` (`derive_candidate_profile(data).role_kind`); задаёт базу
    веса «Управление» (Этап 3), сам не хранится и не выводится из `data` здесь ещё раз, чтобы
    не заводить второй источник его нормализации. `travel_is_dealbreaker` — тот же срез профиля
    (Этап 5 §5.4): явное стоп-условие по командировкам поднимает приоритет `work_format` отдельно
    от того, насколько узко выбран `schedule`. `track=second_job` — фиксированная база
    `SECOND_JOB_WEIGHTS` со сдвигом по ред-флагам и валюте резюме (Э2.4).
    """
    if track == "second_job":
        return _second_job_auto_weights(data)
    pos = getattr(data, "position", None)
    sc = getattr(data, "search_criteria", None)

    schedule = _strip(getattr(pos, "schedule", None))
    grades = _strip(getattr(pos, "grade", None))
    categories = _strip(getattr(pos, "categories", None))

    niches = _strip(getattr(sc, "niches", None))
    target_companies = _strip(getattr(sc, "target_companies", None))
    avoid_companies = _strip(getattr(sc, "avoid_companies", None))

    # Специфичность schedule (Этап 5 §5.4), не его насыщенность количеством: уже выбор = строже
    # предпочтение. Занятость (employment) — мягкий бонус присутствия, не специфичности.
    employment = str(getattr(pos, "employment", "") or "").strip()
    work_signal = _schedule_specificity(schedule) + (0.15 if employment else 0.0)
    if travel_is_dealbreaker:
        work_signal += _TRAVEL_DEALBREAKER_BONUS
    work_signal = min(1.0, work_signal)

    grade_signal = _pool_signal_strength(grades)
    role_signal = _signal_strength(categories, niches)
    company_signal = _pool_signal_strength(target_companies, avoid_companies)

    # Приоритет весов на старте (перед нормализацией) — относительные важности оставшихся
    # трёх сигнальных осей (role_content и management посчитаны отдельно, ниже).
    # Пустые списки компаний → им ниже вес; заполненные форматы/грейды — выше.
    priorities = {
        "work_format": 0.6 + 0.4 * work_signal,
        "grade_match": 0.4 + 0.6 * grade_signal,
        "company": 0.2 + 0.8 * company_signal,
    }

    management_weight = _MANAGEMENT_BASE_BY_ROLE.get(role_kind, _MANAGEMENT_BASE_BY_ROLE["unknown"])
    role_content_weight = round(_ROLE_CONTENT_BASE + _ROLE_CONTENT_SIGNAL_SPAN * role_signal)

    tunable_share = 100 - SALARY_WEIGHT - management_weight - role_content_weight
    total_prior = sum(priorities.values())
    scaled = {k: round(tunable_share * p / total_prior) for k, p in priorities.items()}
    diff = tunable_share - sum(scaled.values())
    if diff != 0:
        top = max(scaled, key=lambda k: scaled[k])
        scaled[top] += diff  # остаток — в наибольший, как `score_breakdown.resolve_weights`

    weights = {
        **DEFAULT_WEIGHTS,
        "salary": SALARY_WEIGHT,
        "management": management_weight,
        "role_content": role_content_weight,
    }
    for key in _OTHER_SIGNAL_KEYS:
        weights[key] = scaled[key]
    return weights


__all__ = [
    "TUNABLE_KEYS",
    "derive_auto_scoring_weights",
]
