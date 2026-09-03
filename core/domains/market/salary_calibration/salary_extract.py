"""LLM: извлечение вилок из батча постов Telegram."""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from core.domains.market.salary_calib import CalibQueueItem, CalibSample
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.money import gross_to_net
from core.platform.observability import event

logger = logging.getLogger(__name__)


class SalaryCalibExtracted(BaseModel):
    """Одна вакансия из батча (ответ LLM)."""

    is_relevant: bool = True
    skip_reason: str = ""
    company: str = ""
    position: str = ""
    grade: str = ""
    company_type: Literal[
        "product",
        "fintech_product",
        "bank",
        "startup",
        "outsource",
        "infra",
        "unknown",
    ] = "unknown"
    salary_min_net: int | None = None
    salary_max_net: int | None = None
    salary_scale: Literal["net", "gross", "unclear"] = "unclear"
    bonus_text: str = ""
    bonus_type: str = ""
    city: str = ""
    work_format: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    note: str = ""


class SalaryCalibBatchResult(BaseModel):
    items: list[SalaryCalibExtracted] = Field(default_factory=list)


_EXTRACT_SYSTEM = """Ты — аналитик рынка труда IT в России (2025–2026).

Из каждого поста Telegram (вакансия с канала) извлеки структурированные данные для калибровки зарплат.

Правила:
- is_relevant=false для: реклама, курсы, вебинары, новости без вакансии, чистый backend без AI/ML/Data, sales/PM без техники.
- is_relevant=true для: ML/LLM/Data/AI Engineer, NLP, RAG, MLOps с ML-фокусом, Prompt/LLM roles.
- salary_min_net / salary_max_net — месячный ОКЛАД в ₽. Если указано «на руки» / net — как есть. Если gross / до НДФЛ — умножь на 0.87 (в note укажи конвертацию).
- Если вилка одна цифра «от X» — min=X, max=null или min=max.
- grade: junior|junior_plus|middle|middle_plus|senior|teamlead|techlead|other
- company_type: product|fintech_product|bank|startup|outsource|infra|unknown
- bonus_text: кратко («15% годовых», «до 2 окладов») или ""
- bonus_type: KPI|обязательная|годовая|квартальная|нет|неясно
- confidence: high если цифры явные, low если догадка

Ответ — СТРОГО JSON:
{"items": [{"is_relevant": true, "skip_reason": "", "company": "", "position": "", "grade": "senior", "company_type": "product", "salary_min_net": 400000, "salary_max_net": 500000, "salary_scale": "net", "bonus_text": "", "bonus_type": "", "city": "", "work_format": "", "confidence": "high", "note": ""}]}

Число элементов items ДОЛЖНО равняться числу постов во входе (по порядку)."""


def _build_user_payload(items: list[CalibQueueItem]) -> str:
    blocks: list[str] = []
    for i, p in enumerate(items, 1):
        ch = p.forward_channel or "unknown"
        text = str(p.raw_text or "")[:3500]
        blocks.append(f"### POST {i} (channel: {ch})\n{text}")
    return f"Извлеки данные из {len(items)} постов.\n\n" + "\n\n".join(blocks)


def _parse_batch(raw: str, n_posts: int) -> SalaryCalibBatchResult:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```"))
    data = json.loads(text)
    if isinstance(data, list):
        data = {"items": data}
    result = SalaryCalibBatchResult.model_validate(data)
    if len(result.items) < n_posts:
        while len(result.items) < n_posts:
            result.items.append(
                SalaryCalibExtracted(is_relevant=False, skip_reason="нет в ответе LLM")
            )
    elif len(result.items) > n_posts:
        result.items = result.items[:n_posts]
    return result


def _normalize_item(item: SalaryCalibExtracted) -> dict:
    d = item.model_dump()
    if not item.is_relevant:
        return d
    smin, smax = item.salary_min_net, item.salary_max_net
    if item.salary_scale == "gross" and smin:
        smin = gross_to_net(smin)
        smax = gross_to_net(smax) if smax else None
        d["salary_min_net"] = smin
        d["salary_max_net"] = smax
        d["salary_scale"] = "net"
        d["note"] = (d.get("note") or "") + " gross→net×0.87"
    if smin and smax and smin > smax:
        d["salary_min_net"], d["salary_max_net"] = smax, smin
    return d


async def extract_salary_batch(items: list[CalibQueueItem]) -> list[CalibSample]:
    """items: [CalibQueueItem, ...] → list[CalibSample] для insert_sample."""
    if not items:
        return []

    user = _build_user_payload(items)
    raw = await ports.llm().complete(
        "salary_extract",
        system=_EXTRACT_SYSTEM,
        user=user,
        temperature=0.3,
    )

    try:
        batch = _parse_batch(raw, len(items))
    except (json.JSONDecodeError, ValidationError) as exc:
        channels = sorted({post.forward_channel or "unknown" for post in items})
        event(
            logger,
            "LLM",
            "Salary calib parse error: %s",
            exc,
            level=logging.WARNING,
            batch_size=len(items),
            channels=",".join(channels),
        )
        raise LlmError(f"Невалидный JSON калибровки: {exc}") from exc

    out: list[CalibSample] = []
    for post, item in zip(items, batch.items, strict=False):
        fields = _normalize_item(item)
        fields["source_channel"] = post.forward_channel or ""
        fields["raw_excerpt"] = str(post.raw_text or "")[:500]
        out.append(CalibSample(account_id=post.account_id, queue_id=post.id, **fields))
    return out
