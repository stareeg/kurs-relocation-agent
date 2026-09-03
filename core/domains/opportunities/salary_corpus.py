"""Воронка кормит корпус калибровки зарплат.

Названная рекрутером вилка (HR-факт) и сумма оффера — такие же наблюдения рынка, как
пересланные в бот посты. Тут парсинг вилки из свободного текста HR-факта и сборка `CalibSample`
с `source='funnel'` + дедуп по `content_hash`, чтобы фоновый HR-пересчёт и повторные правки оффера
не плодили дубли. Так названные HR-вилки и офферы становятся приорами `fetch_segment_prior`.

Best-effort: вызовы обёрнуты в `*_safe`, любая ошибка глушится — кормление корпуса не должно
ронять ни пересчёт скоринга, ни сохранение оффера.
"""

from __future__ import annotations

import logging
import re

from core.domains.market.salary_calib import CalibSample, insert_funnel_sample, text_fingerprint
from core.domains.offers.store import Offer
from core.kernel.money import detect_tax_basis, gross_to_net, to_monthly, to_net
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

# Правдоподобная месячная вилка (₽) — отсекаем мусор/годовые суммы/опечатки до записи в корпус.
_MIN_PLAUSIBLE = 80_000
_MAX_PLAUSIBLE = 3_000_000

# «500-600k» / «500–600 тыс» — обе границы делят суффикс тысяч (общий случай шортката вилки).
_K_RANGE = re.compile(r"(\d{2,4})\s*[-–—]\s*(\d{2,4})\s*(?:k|к|тыс)\b", re.IGNORECASE)
# «500k» / «600 к» / «450 тыс» — суффикс тысяч; и полные числа «450 000» / «600000».
_K_NUM = re.compile(r"(\d[\d\s.]{0,7}?)\s*(?:k|к|тыс)\b", re.IGNORECASE)
_FULL_NUM = re.compile(r"\d[\d\s]{4,}")


def _to_int(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _extract_amounts(text: str) -> list[int]:
    """Все правдоподобные месячные суммы из строки (k-суффикс ×1000 + полные числа)."""
    amounts: list[int] = []
    for m in _K_RANGE.finditer(text):
        for g in (m.group(1), m.group(2)):
            n = _to_int(g)
            if n is not None:
                amounts.append(n * 1000)
    for m in _K_NUM.finditer(text):
        n = _to_int(m.group(1))
        if n is not None:
            amounts.append(n * 1000 if n < 5000 else n)
    for m in _FULL_NUM.finditer(text):
        n = _to_int(m.group(0))
        if n is not None:
            amounts.append(n)
    return [a for a in amounts if _MIN_PLAUSIBLE <= a <= _MAX_PLAUSIBLE]


def parse_net_range(text: str) -> tuple[int | None, int | None, str]:
    """Свободный текст вилки → (min_net, max_net, scale). (None, None, 'unclear') — цифр нет.

    gross/«до вычета» → конвертируем в net (×0.87); net/«на руки» — как есть; неясно — оставляем,
    помечая scale='unclear' (samples хранят net, иной шкалы у поля нет).
    """
    amounts = sorted(set(_extract_amounts(text or "")))
    if not amounts:
        return None, None, "unclear"
    lo, hi = amounts[0], amounts[-1]

    basis = detect_tax_basis(text)
    if basis == "gross":
        lo = gross_to_net(lo) or lo
        hi = gross_to_net(hi) or hi
        scale = "net"
    elif basis == "net":
        scale = "net"
    else:
        scale = "unclear"
    return lo, hi, scale


async def feed_hr_salary_sample(
    vacancy_id: str,
    salary_text: str,
    company_type: str,
    grade: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> bool:
    """Названная HR вилка → funnel-сэмпл (дедуп по content_hash). True — записан новый сэмпл."""
    if not vacancy_id or not (salary_text or "").strip():
        return False
    lo, hi, scale = parse_net_range(salary_text)
    if lo is None:
        return False

    content_hash = text_fingerprint(f"{vacancy_id}|hr|{lo}|{hi}")
    sample = CalibSample(
        account_id=account_id,
        company_type=(company_type or "unknown").strip() or "unknown",
        grade=(grade or "").strip(),
        salary_min_net=lo,
        salary_max_net=hi if hi != lo else None,
        salary_scale=scale,
        confidence="high",
        is_relevant=True,
        note="Вилка со слов HR (воронка).",
        source_channel="funnel:hr",
        raw_excerpt=(salary_text or "")[:500],
        source="funnel",
        content_hash=content_hash,
    )
    inserted = await insert_funnel_sample(sample, db=db)
    if inserted is not None:
        logger.info("ИНГЕСТ HR-вилка в корпус: vacancy=%s, %s-%s net", vacancy_id, lo, hi)
    return inserted is not None


async def feed_offer_sample(
    offer: Offer,
    company_type: str,
    grade: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> bool:
    """Сумма оффера → funnel-сэмпл (дедуп по content_hash). True — записан новый сэмпл."""
    if not offer.vacancy_id or not offer.base_salary:
        return False
    monthly = to_monthly(offer.base_salary, offer.base_salary_period)
    if not (_MIN_PLAUSIBLE <= monthly <= _MAX_PLAUSIBLE):
        return False

    monthly = to_net(monthly, tax_basis=offer.base_salary_tax_basis) or monthly

    content_hash = text_fingerprint(f"{offer.vacancy_id}|offer|{monthly}")
    sample = CalibSample(
        account_id=account_id,
        company=offer.company or None,
        position=offer.position or None,
        company_type=(company_type or "unknown").strip() or "unknown",
        grade=(grade or "").strip(),
        salary_min_net=monthly,
        salary_max_net=None,
        salary_scale="net",
        work_format=offer.work_format or None,
        confidence="high",
        is_relevant=True,
        note="Оклад из оффера (воронка).",
        source_channel="funnel:offer",
        source="funnel",
        content_hash=content_hash,
    )
    inserted = await insert_funnel_sample(sample, db=db)
    if inserted is not None:
        logger.info(
            "ИНГЕСТ оффер в корпус калибровки: vacancy=%s, %s net/мес", offer.vacancy_id, monthly
        )
    return inserted is not None


async def feed_hr_salary_sample_safe(
    vacancy_id: str,
    salary_text: str,
    company_type: str,
    grade: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Best-effort обёртка: глушит исключения (кормление корпуса не валит HR-пересчёт)."""
    try:
        await feed_hr_salary_sample(
            vacancy_id, salary_text, company_type, grade, account_id=account_id, db=db
        )
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.debug("HR-вилка в корпус не записана (best-effort): %s", exc)


__all__ = [
    "parse_net_range",
    "feed_hr_salary_sample",
    "feed_hr_salary_sample_safe",
    "feed_offer_sample",
]
