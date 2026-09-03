"""Версия рубрики скоринга — хэш от весов, role_kind и порогов recommendation.

Этап 5 §5.1 (plans/scoring_precision_2026_08_17.md, D7): веса пересчитываются от резюме на
каждом скоринге (`auto_weights`), поэтому вакансии, оценённые в разные дни, могли получить
разные веса по одним и тем же осям (на проде `work_format` видели 25/21/17 баллов) — доска
сравнивала их как одну шкалу, хотя это разные линейки. Версия — не сами веса, а их отпечаток:
`apply_calibration`/`recompute_salary_axis` штампуют её в каждый пересчитанный `ScoreResult`,
а UI/API сравнивают строку, не расшифровывая процесс её получения.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

# Бампить при изменении алгоритма калибровки (fraction-таблицы уровней, форма порогов и т.п.),
# даже если числа весов не поменялись — иначе одинаковые веса при другой логике посчитались бы
# той же версией рубрики.
RUBRIC_ALGO_VERSION = 1


def compute_weights_version(
    weights: Mapping[str, int],
    *,
    role_kind: str,
    thresholds: tuple[int, int, int],
    track: str = "primary",
) -> str:
    """Веса + role_kind + пороги recommendation → короткий стабильный хэш (12 hex-символов).

    `weights` — уже РЕЗОЛВЛЕННЫЙ словарь (после `score_breakdown.resolve_weights`), не сырой
    вход AppSettings: сумма и набор ключей должны быть каноничны, иначе одна и та же
    эффективная рубрика при разной форме входа считалась бы разными версиями. Сортировка ключей
    делает хэш независимым от порядка dict-обхода. `track` входит в хэш только для второго
    трека — иначе доска сравнивала бы две рубрики как одну линейку, а хэш основной рубрики
    у уже проскоренных карточек не сдвинулся бы от добавления поля.
    """
    payload = {
        "algo": RUBRIC_ALGO_VERSION,
        "weights": {k: int(weights[k]) for k in sorted(weights)},
        "role_kind": role_kind,
        "thresholds": list(thresholds),
    }
    if track != "primary":
        payload["track"] = track
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


__all__ = ["RUBRIC_ALGO_VERSION", "compute_weights_version"]
