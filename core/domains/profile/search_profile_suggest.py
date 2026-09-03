"""Подбор профиля поиска по резюме (шаг 4 universal profile).

Один HITL-вызов: тип роли, рынок из справочника, слайт приоритетов с reason.
Ничего не сохраняет — фронт решает, что принять в PATCH.

Ротация вариантов: `exclude_priorities` (уже выбранное + уже показанное) входит в текст запроса,
а значит и в ключ result-кэша `call.run` — поэтому повторное «Обновить» даёт новую порцию, а не
тот же слайт из кэша. Если модель всё равно вернула почти только старое, делаем ОДИН повторный
вызов с усиленной инструкцией: бюджет сценария — ≤2 вызова (CLAUDE.md §LLM «Quality repair ≤ 1»).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.profile.model import ResumeData
from core.domains.profile.structured_store import read_resume_data_for_account
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

# Сколько новых пунктов считаем достаточным результатом. Слайт из 1-2 ярлыков на экране
# неотличим от «кнопка не сработала» — ниже этого порога имеет смысл один повтор.
MIN_FRESH_PRIORITIES = 3

# Сколько пунктов максимум отдаём фронту (он показывает 6 + «все варианты»).
MAX_PRIORITIES_OUT = 8

# Канон совпадает с frontend MARKET_SEGMENT_SUGGESTIONS / resume-taxonomy.
# Мульти-выбор: несколько отраслей можно выбрать одновременно (UI разделяет/склеивает запятыми).
# «Любые» — значение по умолчанию = без фильтра (пустая строка в market_segment).
MARKET_SEGMENT_OPTIONS: tuple[str, ...] = (
    "Любые",
    "IT",
    "Банки / Финтех",
    "Ритейл / E-commerce",
    "Телеком",
    "Медиа / Продакшн",
    "Маркетинг / Реклама",
    "Образование / EdTech",
    "Производство / Промышленность",
    "Госсектор / GovTech",
    "Здравоохранение / MedTech",
    "Нефтегаз / Энергетика",
)

# Отрасль места работы: тот же справочник, но «Любые» (фильтр поиска) → «Другое»
# (LLM не смогла классифицировать компанию). Зеркало frontend EXPERIENCE_INDUSTRY_OPTIONS.
EXPERIENCE_INDUSTRY_OTHER = "Другое"
EXPERIENCE_INDUSTRY_OPTIONS: tuple[str, ...] = tuple(
    opt for opt in MARKET_SEGMENT_OPTIONS if opt != "Любые"
) + (EXPERIENCE_INDUSTRY_OTHER,)


def coerce_experience_industry(raw: str) -> str:
    """Закрытый список отрасли опыта; пусто остаётся пустым, неизвестное / «Любые» → «Другое»."""
    key = (raw or "").strip()
    if not key:
        return ""
    matched = next(
        (opt for opt in EXPERIENCE_INDUSTRY_OPTIONS if key.casefold() == opt.casefold()),
        None,
    )
    return matched if matched else EXPERIENCE_INDUSTRY_OTHER


ROLE_KIND_OPTIONS: tuple[str, ...] = (
    "Делаю руками",
    "Управляю людьми",
    "И то, и другое",
)

_SYSTEM = """Ты помогаешь кандидату заполнить профиль поиска работы по фактам резюме.

Верни ТОЛЬКО JSON:
{
  "role_kind": "<одна из трёх канонических строк>",
  "market_segment": "<значение из справочника рынков>",
  "priorities": [{"label": "<2-4 слова>", "reason": "<до 60 символов>"}]
}

Правила:
- role_kind — строго одно из: «Делаю руками», «Управляю людьми», «И то, и другое».
  Инженер/дизайнер/разработчик без управления людьми → «Делаю руками».
  PM/руководитель/тимлид с людьми → «Управляю людьми».
  Техлид, совмещение → «И то, и другое».
- market_segment — одно или несколько значений из справочника, через запятую; если
  непонятно — оставь пустым.
- priorities: 6-8 пунктов. label — конкретное направление (не «IT», «работа», «развитие»).
  reason — коротко «из опыта в …» / «из навыков …».
- Не повторяй label из блока exclude.
- Опирайся только на резюме из user-сообщения; не придумывай технологий, которых нет в резюме.
"""


class PrioritySuggestion(BaseModel):
    label: str = ""
    reason: str = ""


class SearchProfileSuggestion(BaseModel):
    role_kind: str = ""
    market_segment: str = ""
    priorities: list[PrioritySuggestion] = Field(default_factory=list)


def _resume_context(data: ResumeData) -> str:
    pos = data.position
    sc = data.search_criteria
    parts: list[str] = []
    if pos.title:
        parts.append(f"Желаемая должность: {pos.title}")
    if pos.categories:
        parts.append(f"Категории: {', '.join(pos.categories)}")
    if pos.grade:
        parts.append(f"Целевой грейд: {', '.join(pos.grade)}")
    if sc.role_kind.strip():
        parts.append(f"Уже выбран тип роли: {sc.role_kind.strip()}")
    if sc.market_segment.strip():
        parts.append(f"Уже выбран рынок: {sc.market_segment.strip()}")
    skills = [s for s in data.key_skills if s.strip()]
    if skills:
        parts.append("Ключевые навыки: " + ", ".join(skills))
    exps = [e for e in data.experience[:5] if e.company or e.position]
    if exps:
        lines = [
            f"- {e.position or '?'} в {e.company or '?'}"
            + (f" ({e.industry})" if e.industry else "")
            for e in exps
        ]
        parts.append("Опыт работы:\n" + "\n".join(lines))
    return "\n".join(parts).strip()


def _normalize_role_kind(raw: str) -> str:
    key = (raw or "").strip()
    for opt in ROLE_KIND_OPTIONS:
        if key.casefold() == opt.casefold():
            return opt
    return ""


def _normalize_market_segment(raw: str) -> str:
    key = (raw or "").strip()
    if not key:
        return ""
    # Мульти-выбор: LLM может вернуть или одно значение, или разделённые запятыми.
    # Каждую часть канонизируем по справочнику.
    parts = [p.strip() for p in key.split(",")]
    canon: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if not p:
            continue
        matched = next(
            (opt for opt in MARKET_SEGMENT_OPTIONS if p.casefold() == opt.casefold()), None
        )
        c = matched if matched else p[:80]
        if c.casefold() not in seen:
            seen.add(c.casefold())
            canon.append(c)
    # «Любые» соло = пустая строка (без фильтра). В комбинации с другими — убираем.
    if len(canon) == 1 and canon[0].casefold() == "любые":
        return ""
    canon = [c for c in canon if c.casefold() != "любые"]
    return ", ".join(canon) if canon else ""


def _build_user(context: str, exclude_clean: list[str], *, insist: bool) -> str:
    """Текст запроса. `insist` — повторная попытка: те же данные, но жёстче про «не повторяйся».

    Блок insist меняет текст, а значит и ключ result-кэша — иначе повтор просто вернул бы
    закэшированный первый ответ.
    """
    exclude_block = (
        "\n\nExclude (не повторять label):\n" + "\n".join(f"- {e}" for e in exclude_clean)
        if exclude_clean
        else ""
    )
    insist_block = (
        "\n\nВНИМАНИЕ: предыдущая попытка вернула почти только пункты из Exclude. Дай ДРУГИЕ "
        "направления — соседние специализации, смежные домены, другие уровни стека из того же "
        "резюме. Ни один label не должен повторять Exclude даже по смыслу."
        if insist
        else ""
    )
    markets = ", ".join(MARKET_SEGMENT_OPTIONS)
    roles = ", ".join(ROLE_KIND_OPTIONS)
    return (
        f"{context}{exclude_block}{insist_block}"
        f"\n\nСправочник рынков: {markets}\nКанон типа роли: {roles}\n"
    )


async def _ask(user: str) -> SearchProfileSuggestion:
    return await ports.llm().structured(
        "resume_search_profile_suggest",
        system=_SYSTEM,
        user=user,
        schema=SearchProfileSuggestion,
        temperature=0.4,
    )


def _collect_fresh(
    items: list[PrioritySuggestion],
    *,
    taken: set[str],
    into: list[PrioritySuggestion],
) -> None:
    """Добавить в `into` только новые пункты; `taken` — казённые casefold-ярлыки (мутируется)."""
    for item in items:
        label = (item.label or "").strip()
        if not label or label.casefold() in taken:
            continue
        taken.add(label.casefold())
        into.append(PrioritySuggestion(label=label, reason=(item.reason or "").strip()[:60]))
        if len(into) >= MAX_PRIORITIES_OUT:
            return


async def suggest_search_profile(
    *,
    account_id: int,
    exclude_priorities: list[str] | None = None,
) -> SearchProfileSuggestion:
    """Слайт профиля поиска аккаунта запроса. Нет ключа → LlmError; пустое резюме → ValueError."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    data = await read_resume_data_for_account(account_id)
    context = _resume_context(data)
    if not context:
        raise ValueError("нет структурированного резюме для подбора профиля")

    exclude_clean = [e.strip() for e in (exclude_priorities or []) if e.strip()]
    result = await _ask(_build_user(context, exclude_clean, insist=False))

    priorities: list[PrioritySuggestion] = []
    taken = {e.casefold() for e in exclude_clean}
    _collect_fresh(result.priorities, taken=taken, into=priorities)

    role_kind = _normalize_role_kind(result.role_kind)
    market_segment = _normalize_market_segment(result.market_segment)

    # Один повтор — только когда исключать было что и модель всё равно почти не дала нового.
    if len(priorities) < MIN_FRESH_PRIORITIES and exclude_clean:
        event(
            logger,
            "ЗАДАЧА",
            "подбор профиля: новых пунктов %d < %d — один повтор с усиленной инструкцией",
            len(priorities),
            MIN_FRESH_PRIORITIES,
            fresh=len(priorities),
            excluded=len(exclude_clean),
        )
        retry = await _ask(_build_user(context, exclude_clean, insist=True))
        _collect_fresh(retry.priorities, taken=taken, into=priorities)
        # Оси профиля от исключений не зависят: берём первый непустой ответ.
        role_kind = role_kind or _normalize_role_kind(retry.role_kind)
        market_segment = market_segment or _normalize_market_segment(retry.market_segment)

    return SearchProfileSuggestion(
        role_kind=role_kind,
        market_segment=market_segment,
        priorities=priorities,
    )


__all__ = [
    "EXPERIENCE_INDUSTRY_OPTIONS",
    "EXPERIENCE_INDUSTRY_OTHER",
    "MARKET_SEGMENT_OPTIONS",
    "MAX_PRIORITIES_OUT",
    "MIN_FRESH_PRIORITIES",
    "ROLE_KIND_OPTIONS",
    "PrioritySuggestion",
    "SearchProfileSuggestion",
    "coerce_experience_industry",
    "suggest_search_profile",
]
