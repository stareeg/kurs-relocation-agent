"""LLM-резолв слабых буллетов резюме батчем.

Прежний путь — `core/resume/gap.py::_is_weak_bullet` — грубая эвристика (нет цифры И нет стема
глагола из жёсткого списка = слабый). Ошибается в обе стороны: буллет «работал с командой из 5
человек» проходит как сильный только из-за цифры, а содержательный буллет без цифры и без
попадающего в список глагола ложно считается слабым. Здесь — один батч-вызов haiku на ВСЕ
буллеты резюме сразу (не по одному вызову на буллет), с тем же fallback-принципом, что и
`funnel_status_llm.py`/`stage_type_llm.py`: LLM первым, regex — страховка при сбое/отсутствии
ключа, не наоборот.
"""

from __future__ import annotations

import json
import logging
import re

from core.config import get_settings
from core.domains.profile.gap import WeakBullet
from core.domains.profile.model import ResumeData
from core.domains.profile.score_tips import normalize_score_tip
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

_SYSTEM_TEMPLATE = """Ты анализируешь буллеты резюме кандидата ({{CANDIDATE_IDENTITY}}), чтобы найти слабые места.

Буллет СЛАБЫЙ, если он полностью поверхностный: никакой конкретики, только общие слова
без содержания. Примеры слабых:
- «Отвечал за качество продукта»
- «Занимался развитием направления»
- «Участвовал в проектах команды»
- «Работал с командой из 5 человек» (цифра про состав, не про результат)

Буллет СИЛЬНЫЙ, если в нём есть ХОТЯ БЫ ОДНО: конкретное действие, названная технология,
результат, масштаб, инструмент, система. Примеры сильных:
- «Стек: Hadoop, Greenplum, ClickHouse через Trino + Airflow» (перечислены инструменты)
- «Infra: OpenShift, Kubernetes, Jenkins (CI/CD), Vault, Kerberos» (названы технологии)
- «Разобрал зависший процесс ревью, вынес блокеры на ретро» (конкретное действие + эффект)
- «Спроектировал DWH-витрины, сократил time-to-market с 2 недель до 4 дней» (действие + метрика)

Будь консервативен: СОМНЕВАЕШЬСЯ — СТАВЬ STRONG. Цель — поймать только реально пустые
общие фразы, а не докопаться до каждого буллета без цифры.

Слабым считай также буллет с **лишними англицизмами** там, где есть русский эквивалент
(«deliver feature», «performance review» без названий продуктов/технологий). Английский
допустим только для имён технологий, фреймворков и брендов.

На вход — пронумерованный список буллетов (в скобках — раздел резюме, для контекста). Верни
ТОЛЬКО JSON, вердикт по КАЖДОМУ номеру:
{"verdicts": [{"i": <номер>, "weak": <bool>, "reason": "<если weak: одна строка — что улучшить и почему; без слов weak/strong/слабый/вердикт; пример: «добавьте технологии и результат»>"}]}
"""


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty LLM response", raw, 0)

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(raw[start : i + 1])

    raise json.JSONDecodeError("no JSON object in LLM response", raw, 0)


async def resolve_weak_bullets_llm(
    bullets: list[tuple[str, str, int | None, str]],
    *,
    resume: ResumeData | None = None,
    llm: ports.LlmPort | None = None,
) -> list[WeakBullet] | None:
    """Слабые буллеты по вердикту LLM, или `None` при недоступности/сбое LLM.

    `bullets` — (section, ref, index, text) по ВСЕМ буллетам резюме (не только тем, что regex
    уже посчитал слабыми — иначе LLM унаследует слепые зоны regex вместо того, чтобы их чинить).
    `None` — сигнал звонящему коду упасть на regex-fallback (`find_weak_bullets`), не решение
    само по себе, как в `stage_type_llm.py`.
    `llm` — подмена порта в тестах; по умолчанию связанный порт процесса.
    """
    if not bullets:
        return []
    if not get_settings().openrouter_api_key:
        return None

    numbered = "\n".join(
        f"{i}. [{ref}] {text}" for i, (_section, ref, _index, text) in enumerate(bullets, start=1)
    )

    from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity

    system = _SYSTEM_TEMPLATE.replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume)
    )

    port = llm or ports.llm()
    content = ""
    last_llm_exc: LlmError | None = None
    # §13: у weak_bullets budget_ms короткий (15с) — вместо одного долгого таймаута две короткие
    # попытки; зависший сетевой запрос отваливается быстро и не съедает второй шанс на ответ.
    for _attempt in range(2):
        try:
            content = await port.complete(
                "weak_bullets",
                system=system,
                user=numbered,
                temperature=0.1,
                max_tokens=1024 + 80 * len(bullets),
            )
            last_llm_exc = None
            break
        except LlmError as exc:
            last_llm_exc = exc
    if last_llm_exc is not None:
        logger.warning("LLM resolve weak_bullets failed after retry: %s", last_llm_exc)
        return None

    try:
        data = _extract_json(content)
        raw_verdicts = data.get("verdicts")
        if not isinstance(raw_verdicts, list):
            raise KeyError("verdicts")

        out: list[WeakBullet] = []
        for item in raw_verdicts:
            if not isinstance(item, dict) or not bool(item.get("weak")):
                continue
            i = int(item.get("i", 0))
            if not (1 <= i <= len(bullets)):
                continue
            section, ref, index, text = bullets[i - 1]
            reason = normalize_score_tip(str(item.get("reason", "")).strip()) or None
            out.append(WeakBullet(section=section, ref=ref, index=index, text=text, reason=reason))
        return out
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        snippet = (content[:200] + "…") if content else "(пусто)"
        logger.warning("LLM resolve weak_bullets failed: %s — ответ: %s", exc, snippet)
        return None


__all__ = ["resolve_weak_bullets_llm"]
