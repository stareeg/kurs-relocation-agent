"""Решение «кого автоотклик берёт сам, кого — на ручной разбор, кого — не трогает».

Чистая функция без I/O — тестируется без БД. Источники истины по бокам (пропущена ли
вакансия, какой у неё статус/скор) вызывающая сторона передаёт через `Job` — гейт сам
в БД не ходит и о площадках не знает (площадку уже выбрал вызывающий, передав нужный
`AutoApplyPlatformConfig`).
"""

from __future__ import annotations

from typing import Literal

from core.domains.opportunities.jobs import Job
from core.domains.pipeline.auto_apply.config import AutoApplyPlatformConfig
from core.kernel.schemas.funnel import FunnelStatus

AutoApplyDecision = Literal["auto", "manual_review", "excluded", "applied"]


def classify_for_auto_apply(
    job: Job,
    *,
    config: AutoApplyPlatformConfig,
    override: Literal["auto", "manual_review"] | None = None,
) -> AutoApplyDecision:
    """Классифицировать вакансию для очереди автооткликов одной площадки.

    Порядок проверок — от жёстких инвариантов к порогу скора:
    1. Площадка выключена в настройках → excluded.
    2. Пропущена (`job.skipped` — `skipped_vacancies`, обычно ручное решение) ИЛИ гейт
       скоринга (`recommendation == "skip"`, включает авто-гейт по `avoid_companies` —
       см. `opportunities.rules`) → excluded. Решение «не подавать» уже принято, автоотклик
       не переписывает его — ни ручной пропуск, ни гейт скоринга.
    3. Не в статусе «Просмотрено» (уже отклик/дальше по воронке/архив) → excluded — нечего
       откликать, воронка уже двинулась другим путём (в т.ч. вручную, до автооткликов).
    4. Нет скора → excluded — не на чем принимать решение.
    5. `override` (Фаза E редизайна «Расширения» — ручной квик-экшен «переместить») задан →
       он и есть ответ, минуя порог скора. Персистится вызывающей стороной отдельно
       (`overrides.py`) — эта функция сама в БД не ходит, только применяет то, что ей передали.
       Проверяется ПОСЛЕ пп.1-4: оверрайд выбирает между auto/manual_review, когда оба варианта
       легальны, но не оживляет вакансию, которую воронка/гейт/скип уже вывели из игры.
    6. Скор ≥ `min_score` → auto.
    7. Иначе → manual_review — один порог, всё ниже него владелец разбирает сам.

    Порог ровно один (2026-09-01, owner's spec). Раньше их было два — `min_score` и полоса
    `manual_review_band` под ним, а всё ниже полосы отбрасывалось: два ползунка в UI, из
    которых второй никто не понимал, и тихая потеря вакансий между «не авто» и «не показывать».
    Теперь `manual_review_band` не читается (легаси-поле конфига, как `daily_cap`): «не
    дотянул до автоотклика» и «не показывать вовсе» — разные решения, и второе принимает
    человек кнопкой «Пропуск» (`job.skipped`, п.2), а не порог.
    """
    if not config.enabled:
        return "excluded"
    if job.skipped or job.recommendation == "skip":
        return "excluded"
    if (job.status or "").strip() != FunnelStatus.VIEWED.value:
        return "excluded"
    score = job.overall_score
    if score is None:
        return "excluded"
    if override is not None:
        return override
    if score >= config.min_score:
        return "auto"
    return "manual_review"


__all__ = ["AutoApplyDecision", "classify_for_auto_apply"]
