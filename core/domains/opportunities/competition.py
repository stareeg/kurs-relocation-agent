"""Под-скор «шанс на отклик» (Этап 6 §6.2, plans/scoring_precision_2026_08_17.md).

Параллельный сигнал поверх `ScoreResult`, тот же принцип, что у `remote_feasibility.py`:
отдельное поле, НЕ входит в `overall_score`. Разница — здесь нет LLM-вызова вообще:
детерминированная арифметика по трём полям, которые уже приезжают с площадки
(`total_responses`/`published_at`/`letter_required`), синхронная, без сети.

Не вес в 100 баллах — намеренно (план §6.2): вес без измеренной корреляции с реальными исходами
владельца — это ещё один недискриминирующий вес, а таких на проде уже было три (D2/D6/D7 из
аудита). Корреляция измеряется на Этапе 7, вес по её итогам добавляется отдельным шагом.

Пороги ниже — первая грубая прикидка (раунд-числа), НЕ калиброваны по проду: живая проверка
2026-08-18 показала, что hh.ru перестал отдавать счётчик откликов на странице вакансии вовсе
(`total_responses` = None почти всегда, level="unknown") — калибровать пороги не по чему, пока
Этап 6.1 (SERP-бэкафилл + discovery) не наберёт объём данных.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from core.domains.opportunities.models import CompetitionInsight

_RU_MONTHS_GENITIVE = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_PUBLISHED_AT_RE = re.compile(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})")

# Скорость откликов (в день) — используется, когда известна дата публикации.
_FAVORABLE_RATE_PER_DAY = 1.5
_CROWDED_RATE_PER_DAY = 5.0
# Сырой счётчик без даты — грубее (даты может не быть; не блокируем сигнал целиком).
_FAVORABLE_RAW = 5
_CROWDED_RAW = 20


def parse_published_at(text: str | None) -> date | None:
    """«21 мая 2026» → date. Формат, который отдаёт `parseVacancyPublishedAt` в selectors.ts."""
    if not text:
        return None
    match = _PUBLISHED_AT_RE.search(text.strip().lower())
    if not match:
        return None
    day_s, month_word, year_s = match.groups()
    month = _RU_MONTHS_GENITIVE.get(month_word)
    if month is None:
        return None
    try:
        return date(int(year_s), month, int(day_s))
    except ValueError:
        return None


def compute_competition_insight(
    *,
    total_responses: int | None,
    published_at: str | None,
    letter_required: bool | None,
) -> CompetitionInsight:
    """Чистая функция, без I/O — безопасно звать синхронно прямо в горячем пути скоринга."""
    if total_responses is None or total_responses < 0:
        return CompetitionInsight(
            level="unknown", reasoning="нет данных о числе откликов на вакансию"
        )

    pub_date = parse_published_at(published_at)
    if pub_date is not None:
        age_days = max((datetime.now(UTC).date() - pub_date).days, 0)
        rate = total_responses / max(age_days, 1)
        if rate < _FAVORABLE_RATE_PER_DAY:
            level = "favorable"
        elif rate > _CROWDED_RATE_PER_DAY:
            level = "crowded"
        else:
            level = "neutral"
        reasoning = f"{total_responses} откликов за {age_days} дн. (~{rate:.1f} в день)"
    else:
        age_days = None
        rate = None
        if total_responses < _FAVORABLE_RAW:
            level = "favorable"
        elif total_responses > _CROWDED_RAW:
            level = "crowded"
        else:
            level = "neutral"
        reasoning = f"{total_responses} откликов, дата публикации неизвестна — оценка грубая"

    # Обязательное сопроводительное отсеивает часть случайных откликов — сдвигаем на ступень
    # мягче (не пересчитываем level с нуля: письмо не отменяет уже посчитанный объём заявок).
    if letter_required:
        if level == "crowded":
            level = "neutral"
            reasoning += "; сопроводительное письмо отсеивает часть претендентов"
        elif level == "neutral":
            level = "favorable"
            reasoning += "; сопроводительное письмо отсеивает часть претендентов"

    return CompetitionInsight(
        level=level,
        responses_per_day=round(rate, 2) if rate is not None else None,
        age_days=age_days,
        reasoning=reasoning,
    )
