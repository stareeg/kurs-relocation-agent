"""Снимок навыков: «мои + разрывы» в одной таблице.

Заменяет две несвязанные поверхности («Спрос на мои навыки» и «предложенные навыки») одним
ранжированным списком, где «есть у меня» — состояние строки, а не отдельный блок:

- `have`   — есть в резюме, требуют в выборке (бывший «Спрос на мои навыки», но по канону
  требований, а не подстрокой: `Git` больше не ловит `GitLab`);
- `add`    — требуют в выборке, в резюме нет;
- `drop`   — есть в резюме, не требует никто из выборки;
- `rename` — по сути есть, в вакансиях пишут другим словом.

Сборка в два прохода: (1) детерминированный агрегат спроса по кэшу требований вакансий
(`opportunities.requirements`) — навык, скольким вакансиям выборки он нужен, какие
компании, обязательный/желательный; (2) один `reasoning`-вызов раскладывает разрывы по классам
действия (не больше `MAX_ACTIONS`) с учётом резюме целиком. Числа LLM не придумывает — они уже
посчитаны на шаге (1) и подставляются в ответ после; модель отвечает только за отбор, класс и
формулировку причины.

Персист — `resume_skill_snapshots` (шапка) + `resume_skill_suggestions` (строки, миграция
0082). `user_state` (`accepted`/`hidden`) переживает пересборку: `save_snapshot` переносит его
из предыдущего снимка по канону навыка (Решение 6 плана) — иначе скрытое предложение
возвращалось бы на каждый пересчёт.

Автопересборка (Решение 2) — `maybe_auto_refresh_for_new_vacancies` /
`maybe_auto_refresh_for_resume_change`, вызываются из подписок `core.domains.profile.events` на
`VacancyScored`/`ResumeUpdated`. `GET` (`load_skills_panel`) сам никогда не пересобирает — только
читает и объясняет `stale` словами.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.opportunities.models import SkillRequirement
from core.domains.opportunities.requirements import load_requirements_bulk
from core.domains.opportunities.skill_canon import canonical_skill_name
from core.domains.profile.ats_fit import HH_KEY_SKILLS_LIMIT
from core.domains.profile.model import ResumeData
from core.domains.profile.skills_corpus import (
    SelectionVacancy,
    describe_selection,
    load_selection_corpus,
    plural_vacancies,
)
from core.domains.profile.structured_store import read_resume_data_for_account
from core.kernel import ports
from core.kernel.hashing import input_digest
from core.platform.db.pool import Executor, get_pool, row_to_dict
from core.platform.observability import event
from core.platform.repo.settings import get_setting

logger = logging.getLogger(__name__)

# Пороги автопересборки (Решение 2) — в `app_settings`, не в коде: владелец может
# подвинуть без правки Python, как и `skills_selection_min_score`.
DEFAULT_NEW_VACANCIES_THRESHOLD = 10
SETTING_KEY_NEW_VACANCIES_THRESHOLD = "skills_snapshot_new_vacancies_threshold"
DEFAULT_MIN_REFRESH_INTERVAL_HOURS = 6
SETTING_KEY_MIN_REFRESH_INTERVAL_HOURS = "skills_snapshot_min_interval_hours"

FEATURE = "resume_skill_suggest"
# Ранговый потолок и в снимке, и в промпте (Решение из S-04, риск «блок снова превратится
# в свалку» из раздела «Риски» плана): предложений должно быть мало настолько, чтобы блок
# читался за один взгляд.
MAX_ACTIONS = 8
# Сколько сильнейших по спросу add-кандидатов вообще показывать модели — не весь хвост
# длинного корпуса, только то, что реально может попасть в топ-8.
_MAX_ADD_CANDIDATES = 20

SkillState = Literal["have", "add", "drop", "rename"]
UserState = Literal["pending", "accepted", "hidden"]
Importance = Literal["required", "preferred"]


class SkillDemand(BaseModel):
    """Детерминированный агрегат спроса по одному канону навыка в выборке (S-01+S-02+S-03)."""

    skill: str
    demand_count: int
    importance: Importance
    companies: list[str] = Field(default_factory=list)


class SkillSuggestionRow(BaseModel):
    """Одна строка снимка — состояние одного навыка (держу/добавить/лишний/переименовать)."""

    skill: str
    state: SkillState
    renames_to: str | None = None
    importance: Importance | None = None
    demand_count: int = 0
    demand_total: int = 0
    companies: list[str] = Field(default_factory=list)
    rationale: str = ""
    user_state: UserState = "pending"
    state_at: datetime | None = None


class SkillSnapshot(BaseModel):
    """Снимок целиком: шапка + все строки (have — сколько есть, действия — не больше 8).

    `resume_fp` и `vacancy_ids` не показываются в UI — это вход порога автопересборки:
    `resume_fp` сравнивается со свежим `resume_skills_fingerprint()` на `ResumeUpdated`,
    `vacancy_ids` — с текущей выборкой на `VacancyScored`, чтобы посчитать «+N новых вакансий».
    """

    id: int | None = None
    input_fp: str = ""
    resume_fp: str = ""
    corpus_size: int = 0
    selection_rule: str = ""
    created_at: datetime | None = None
    vacancy_ids: list[str] = Field(default_factory=list)
    rows: list[SkillSuggestionRow] = Field(default_factory=list)


class SkillActionLlm(BaseModel):
    """Одно действие в ответе LLM — до постпроцессинга/клампа."""

    skill: str = Field(
        description="Для add — точное название из кандидатов на добавление; "
        "для drop/rename — точное текущее написание из кандидатов на удаление"
    )
    action: Literal["add", "drop", "rename"]
    renames_to: str = Field(
        default="", description="Только для rename — точное название из кандидатов на добавление"
    )
    rationale: str = Field(default="", description="Одна короткая строка — почему")


class SkillSuggestLlm(BaseModel):
    """Structured-выход фичи `resume_skill_suggest`."""

    actions: list[SkillActionLlm] = Field(default_factory=list)


def _canon_key(name: str) -> str:
    return canonical_skill_name(name).casefold()


def build_demand(
    selection: list[SelectionVacancy],
    requirements_by_vacancy: dict[str, list[SkillRequirement]],
) -> list[SkillDemand]:
    """Спрос по выборке: навык (по канону S-03) → скольким вакансиям нужен, кем, насколько
    обязательно. Один навык считается максимум раз на вакансию, даже если вакансия
    упомянула его дважды под разными написаниями.

    Сортировка по убыванию спроса — порядок один и тот же для `have`/`add`/`drop` (Решение из
    модели плана «сортировка одна, так что переключение фильтра не меняет смысл»).
    """
    counts: dict[str, int] = defaultdict(int)
    required_counts: dict[str, int] = defaultdict(int)
    companies: dict[str, list[str]] = defaultdict(list)
    seen_company: dict[str, set[str]] = defaultdict(set)
    display_name: dict[str, str] = {}

    for vac in selection:
        reqs = requirements_by_vacancy.get(vac.vacancy_id, [])
        seen_in_vacancy: set[str] = set()
        for req in reqs:
            canon = canonical_skill_name(req.skill)
            key = canon.casefold()
            display_name.setdefault(key, canon)
            if key in seen_in_vacancy:
                continue
            seen_in_vacancy.add(key)
            counts[key] += 1
            if req.importance == "required":
                required_counts[key] += 1
            company = (vac.company or "").strip()
            if company and company not in seen_company[key]:
                seen_company[key].add(company)
                companies[key].append(company)

    demand = [
        SkillDemand(
            skill=display_name[key],
            demand_count=cnt,
            importance="required" if required_counts[key] > 0 else "preferred",
            companies=companies[key],
        )
        for key, cnt in counts.items()
    ]
    demand.sort(key=lambda d: d.demand_count, reverse=True)
    return demand


def _classify_current_skills(
    key_skills: list[str],
    demand_by_key: dict[str, SkillDemand],
    demand_total: int,
) -> tuple[list[SkillSuggestionRow], dict[str, SkillDemand]]:
    """Текущие теги резюме → строки `have` (спрос > 0) и кандидаты на `drop` (спрос == 0).

    Сверка идёт по канону, не по `casefold()` в лоб — дефект 1 из раздела 0 плана
    (`Git` не должен ловить `GitLab`, а `k8s` в резюме должен считаться `Kubernetes` из
    требований).
    """
    have_rows: list[SkillSuggestionRow] = []
    drop_candidates: dict[str, SkillDemand] = {}
    seen: set[str] = set()
    for raw in key_skills:
        name = (raw or "").strip()
        if not name:
            continue
        key = _canon_key(name)
        if key in seen:
            continue
        seen.add(key)
        demand = demand_by_key.get(key)
        if demand is not None and demand.demand_count > 0:
            have_rows.append(
                SkillSuggestionRow(
                    skill=name,
                    state="have",
                    importance=demand.importance,
                    demand_count=demand.demand_count,
                    demand_total=demand_total,
                    companies=demand.companies,
                )
            )
        else:
            drop_candidates[key] = SkillDemand(
                skill=name, demand_count=0, importance="preferred", companies=[]
            )
    return have_rows, drop_candidates


def _add_candidates(
    key_skills: list[str],
    demand: list[SkillDemand],
    *,
    limit: int = _MAX_ADD_CANDIDATES,
) -> dict[str, SkillDemand]:
    """Востребованные навыки, которых ещё нет в резюме — топ по спросу, не весь хвост."""
    current_keys = {_canon_key(s) for s in key_skills if s and s.strip()}
    out: dict[str, SkillDemand] = {}
    for d in demand:
        key = _canon_key(d.skill)
        if key in current_keys:
            continue
        out[key] = d
        if len(out) >= limit:
            break
    return out


@lru_cache(maxsize=1)
def _load_prompt_template(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Промпт не найден: {path} (CWD={Path.cwd()}). Проверь путь в core.domains.profile.llm."
        )
    return path.read_text(encoding="utf-8")


def _load_prompt(path_str: str, *, data: ResumeData) -> str:
    from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity

    identity = load_candidate_identity(data=data)
    return _load_prompt_template(path_str).replace(CANDIDATE_IDENTITY_TOKEN, identity)


def _format_candidates(items: list[SkillDemand], demand_total: int, *, with_demand: bool) -> str:
    if not items:
        return "(нет)"
    lines: list[str] = []
    for d in items:
        if with_demand:
            companies = ", ".join(d.companies[:5]) or "—"
            lines.append(
                f"- {d.skill}: {d.demand_count}/{demand_total}, {d.importance}, "
                f"компании: {companies}"
            )
        else:
            lines.append(f"- {d.skill}: 0/{demand_total}")
    return "\n".join(lines)


async def _suggest_actions(
    *,
    data: ResumeData,
    add_candidates: dict[str, SkillDemand],
    drop_candidates: dict[str, SkillDemand],
    demand_total: int,
    slots_free: int,
    llm: ports.LlmPort | None = None,
) -> list[SkillActionLlm]:
    """Один `reasoning`-вызов: разложить кандидатов по действиям. Пустые кандидаты — без LLM."""
    if not add_candidates and not drop_candidates:
        return []

    from core.domains.profile.llm import SKILL_SUGGEST

    port = llm or ports.llm()
    system = _load_prompt(SKILL_SUGGEST, data=data)
    role = (data.position.title or "").strip()
    niches = ", ".join(data.search_criteria.niches or []) if data.search_criteria else ""
    user = (
        f"Целевая роль: {role or '(не указана)'}\n"
        f"Ниши: {niches or '(не указаны)'}\n"
        f"Свободных слотов key_skills: {slots_free}/{HH_KEY_SKILLS_LIMIT}\n\n"
        "Кандидаты на добавление (требует выборка, в резюме нет):\n"
        f"{_format_candidates(list(add_candidates.values()), demand_total, with_demand=True)}\n\n"
        "Кандидаты на удаление (есть в резюме, не требует никто из выборки):\n"
        f"{_format_candidates(list(drop_candidates.values()), demand_total, with_demand=False)}\n\n"
        f"Верни JSON по схеме: не больше {MAX_ACTIONS} действий суммарно."
    )
    result = await port.structured(
        FEATURE,
        system=system,
        user=user,
        schema=SkillSuggestLlm,
        tags=("profile", "skill_suggest"),
    )
    if not isinstance(result, SkillSuggestLlm):  # pragma: no cover
        raise TypeError(f"resume_skill_suggest вернул неожиданный тип: {type(result).__name__}")
    return result.actions


def clamp_actions(
    actions: list[SkillActionLlm],
    *,
    add_candidates: dict[str, SkillDemand],
    drop_candidates: dict[str, SkillDemand],
    demand_total: int,
    current_count: int,
    hh_limit: int = HH_KEY_SKILLS_LIMIT,
    limit: int = MAX_ACTIONS,
) -> list[SkillSuggestionRow]:
    """Детерминированный постпроцессинг действий LLM: три класса действий (add/drop/rename)
    и hh-лимит слотов вместо простого add/remove.

    - `add`/`drop`/`rename` — только из предложенных кандидатов, точное совпадение по канону,
      без дублей;
    - `add` не может занять слот, которого нет: разрешено, только пока `current_count -
      принятые drop < hh_limit` (Решение 7 плана — «обмен внутри строки», при 30/30 без drop
      добавить нечего);
    - `rename` слот-нейтрален (одна строка меняет имя, а не занимает вторую);
    - суммарно не больше `limit` действий, порядок — приоритет LLM (add_candidates/demand уже
      отсортированы по спросу, drop_candidates — как их вернула модель).
    """
    drop_rows: list[SkillSuggestionRow] = []
    rename_rows: list[SkillSuggestionRow] = []
    add_rows: list[SkillSuggestionRow] = []
    seen_drop: set[str] = set()
    seen_add: set[str] = set()

    for act in actions:
        name = (act.skill or "").strip()
        if not name:
            continue
        key = _canon_key(name)
        if act.action == "drop":
            cand = drop_candidates.get(key)
            if cand is None or key in seen_drop:
                continue
            seen_drop.add(key)
            drop_rows.append(
                SkillSuggestionRow(
                    skill=cand.skill,
                    state="drop",
                    demand_count=0,
                    demand_total=demand_total,
                    rationale=(act.rationale or "").strip(),
                )
            )
        elif act.action == "rename":
            old_cand = drop_candidates.get(key)
            new_key = _canon_key(act.renames_to) if (act.renames_to or "").strip() else ""
            new_cand = add_candidates.get(new_key) if new_key else None
            if old_cand is None or new_cand is None or key in seen_drop or new_key in seen_add:
                continue
            seen_drop.add(key)
            seen_add.add(new_key)
            rename_rows.append(
                SkillSuggestionRow(
                    skill=old_cand.skill,
                    state="rename",
                    renames_to=new_cand.skill,
                    importance=new_cand.importance,
                    demand_count=new_cand.demand_count,
                    demand_total=demand_total,
                    companies=new_cand.companies,
                    rationale=(act.rationale or "").strip(),
                )
            )
        elif act.action == "add":
            cand = add_candidates.get(key)
            if cand is None or key in seen_add:
                continue
            seen_add.add(key)
            add_rows.append(
                SkillSuggestionRow(
                    skill=cand.skill,
                    state="add",
                    importance=cand.importance,
                    demand_count=cand.demand_count,
                    demand_total=demand_total,
                    companies=cand.companies,
                    rationale=(act.rationale or "").strip(),
                )
            )

    budget = limit
    drop_rows = drop_rows[:budget]
    budget -= len(drop_rows)
    rename_rows = rename_rows[:budget]
    budget -= len(rename_rows)

    # Слоты: rename нейтрален, drop освобождает, add занимает. При current_count == hh_limit и
    # пустом drop_rows slots_free == 0 -> add не показывается вовсе (Решение 7).
    slots_free = max(0, hh_limit - current_count + len(drop_rows))
    add_rows = add_rows[: min(budget, slots_free)]

    return drop_rows + rename_rows + add_rows


def _input_fingerprint(key_skills: list[str], selection: list[SelectionVacancy]) -> str:
    """Отпечаток входа снимка: набор тегов резюме + состав выборки. Не хранит порядок/текст —
    только идентичность входа. Используется `load_skills_panel` для флага `stale` на GET."""
    h = hashlib.sha256()
    h.update("|".join(sorted(s.casefold() for s in key_skills if s.strip())).encode("utf-8"))
    for vacancy_id in sorted(v.vacancy_id for v in selection):
        h.update(vacancy_id.encode("utf-8"))
    return h.hexdigest()[:16]


def resume_skills_fingerprint(data: ResumeData) -> str:
    """«Skills-отпечаток» резюме (Решение 2): что решает пересборку снимка на
    `ResumeUpdated` — key_skills, целевая роль, критерии поиска, тексты опыта, «Обо мне».

    Телефон, образование и языки сюда не входят и не должны: они не меняют ни спрос (S-04
    считает его по выборке вакансий), ни контекст `resume_skill_suggest` (роль/ниши/резюме
    целиком уже включают эти поля отдельно) — их правка не должна расходовать LLM-вызов
    на автопересборку.
    """
    key_skills_part = "|".join(sorted(s.strip().casefold() for s in data.key_skills if s.strip()))
    experience_part = "\x1f".join(
        f"{exp.company}\x1e{exp.position}\x1e{exp.description}" for exp in data.experience
    )
    return input_digest(
        key_skills_part,
        data.position.title.strip(),
        data.search_criteria.model_dump_json(),
        experience_part,
        data.about.strip(),
    )


def count_new_vacancies(previous: SkillSnapshot | None, selection: list[SelectionVacancy]) -> int:
    """Сколько вакансий текущей выборки не входили в `previous.vacancy_ids` — «+N новых
    вакансий с прошлого разбора» (порог 1). Без снимка — вся выборка «новая»."""
    known = set(previous.vacancy_ids) if previous is not None else set()
    return sum(1 for v in selection if v.vacancy_id not in known)


def _min_interval_elapsed(previous: SkillSnapshot | None, *, min_interval_hours: float) -> bool:
    """Нижняя граница автопересборки — не чаще раза в `min_interval_hours`. Ручной
    «Пересобрать» её не спрашивает — он зовёт `refresh_snapshot` напрямую."""
    if previous is None or previous.created_at is None:
        return True
    created_at = (
        previous.created_at
        if previous.created_at.tzinfo
        else previous.created_at.replace(tzinfo=UTC)
    )
    return (datetime.now(UTC) - created_at).total_seconds() >= min_interval_hours * 3600


async def _load_new_vacancies_threshold(*, account_id: int, db: Executor | None = None) -> int:
    value = await get_setting(
        SETTING_KEY_NEW_VACANCIES_THRESHOLD,
        default=DEFAULT_NEW_VACANCIES_THRESHOLD,
        account_id=account_id,
        db=db,
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_NEW_VACANCIES_THRESHOLD


async def _load_min_refresh_interval_hours(*, account_id: int, db: Executor | None = None) -> float:
    value = await get_setting(
        SETTING_KEY_MIN_REFRESH_INTERVAL_HOURS,
        default=DEFAULT_MIN_REFRESH_INTERVAL_HOURS,
        account_id=account_id,
        db=db,
    )
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_REFRESH_INTERVAL_HOURS


async def build_snapshot(
    *,
    account_id: int,
    data: ResumeData | None = None,
    db: Executor | None = None,
    llm: ports.LlmPort | None = None,
) -> SkillSnapshot:
    """Собрать снимок целиком: агрегат спроса (детерминированно) + действия (один LLM-вызов).

    Не сохраняет — `save_snapshot` отдельно, чтобы вызывающий мог сравнить с текущим снимком
    (пересборка по порогу — E-02, здесь только сборка).
    """
    db = db or get_pool()
    if data is None:
        data = await read_resume_data_for_account(account_id, db=db)
    selection = await load_selection_corpus(account_id=account_id, data=data, db=db)
    selection_rule = await describe_selection(account_id=account_id, data=data, db=db)
    req_by_vacancy = await load_requirements_bulk([v.vacancy_id for v in selection], db=db)

    demand = build_demand(selection, req_by_vacancy)
    demand_by_key = {_canon_key(d.skill): d for d in demand}
    demand_total = len(selection)

    key_skills = [s for s in (data.key_skills or []) if s and s.strip()]
    have_rows, drop_candidates = _classify_current_skills(key_skills, demand_by_key, demand_total)
    add_candidates = _add_candidates(key_skills, demand)

    actions = await _suggest_actions(
        data=data,
        add_candidates=add_candidates,
        drop_candidates=drop_candidates,
        demand_total=demand_total,
        slots_free=max(0, HH_KEY_SKILLS_LIMIT - len(key_skills)),
        llm=llm,
    )
    action_rows = clamp_actions(
        actions,
        add_candidates=add_candidates,
        drop_candidates=drop_candidates,
        demand_total=demand_total,
        current_count=len(key_skills),
    )

    event(
        logger,
        "LLM",
        "skill_suggest: %d действий из %d предложенных (add=%d, drop=%d кандидатов)",
        len(action_rows),
        len(actions),
        len(add_candidates),
        len(drop_candidates),
        actions_kept=len(action_rows),
        actions_proposed=len(actions),
        add_candidates=len(add_candidates),
        drop_candidates=len(drop_candidates),
        have=len(have_rows),
        corpus_size=len(selection),
    )

    return SkillSnapshot(
        input_fp=_input_fingerprint(key_skills, selection),
        resume_fp=resume_skills_fingerprint(data),
        corpus_size=len(selection),
        selection_rule=selection_rule,
        vacancy_ids=sorted(v.vacancy_id for v in selection),
        rows=have_rows + action_rows,
    )


async def load_latest_snapshot(
    *, account_id: int, db: Executor | None = None
) -> SkillSnapshot | None:
    """Последний сохранённый снимок аккаунта запроса целиком. `None` — снимков ещё не было."""
    db = db or get_pool()
    header = await db.fetchrow(
        "select id, input_fp, resume_fp, corpus_size, selection_rule, vacancy_ids, created_at "
        "from resume_skill_snapshots where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    if header is None:
        return None
    rows = await db.fetch(
        "select skill, state, renames_to, importance, demand_count, demand_total, "
        "companies, rationale, user_state, state_at "
        "from resume_skill_suggestions where snapshot_id = $1 "
        "order by demand_count desc, id",
        header["id"],
    )
    return SkillSnapshot(
        id=header["id"],
        input_fp=header["input_fp"],
        resume_fp=header["resume_fp"],
        corpus_size=header["corpus_size"],
        selection_rule=header["selection_rule"],
        created_at=header["created_at"],
        vacancy_ids=header["vacancy_ids"],
        rows=[SkillSuggestionRow(**row_to_dict(r)) for r in rows],
    )


async def save_snapshot(
    snapshot: SkillSnapshot, *, account_id: int, db: Executor | None = None
) -> SkillSnapshot:
    """Записать снимок аккаунта запроса новой шапкой + строками. `user_state` (`accepted`/
    `hidden`) переносится из предыдущего снимка ЭТОГО аккаунта по канону навыка (Решение 6) —
    иначе скрытое предложение вернулось бы с пометкой `pending` на каждую пересборку."""
    db = db or get_pool()
    previous = await load_latest_snapshot(account_id=account_id, db=db)
    carried_state = {
        _canon_key(r.skill): r.user_state
        for r in (previous.rows if previous else [])
        if r.user_state != "pending"
    }

    header = await db.fetchrow(
        "insert into resume_skill_snapshots "
        "(account_id, input_fp, resume_fp, corpus_size, selection_rule, vacancy_ids) "
        "values ($1, $2, $3, $4, $5, $6) "
        "returning id, input_fp, resume_fp, corpus_size, selection_rule, vacancy_ids, created_at",
        account_id,
        snapshot.input_fp,
        snapshot.resume_fp,
        snapshot.corpus_size,
        snapshot.selection_rule,
        snapshot.vacancy_ids,
    )
    assert header is not None
    snapshot_id = header["id"]

    saved_rows: list[SkillSuggestionRow] = []
    for row in snapshot.rows:
        user_state = carried_state.get(_canon_key(row.skill), row.user_state)
        db_row = await db.fetchrow(
            "insert into resume_skill_suggestions "
            "(account_id, snapshot_id, skill, state, renames_to, importance, demand_count, "
            " demand_total, companies, rationale, user_state, state_at) "
            "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11, "
            "case when $11 <> 'pending' then now() else null end) "
            "returning skill, state, renames_to, importance, demand_count, demand_total, "
            "companies, rationale, user_state, state_at",
            account_id,
            snapshot_id,
            row.skill,
            row.state,
            row.renames_to,
            row.importance,
            row.demand_count,
            row.demand_total,
            row.companies,
            row.rationale,
            user_state,
        )
        assert db_row is not None
        saved_rows.append(SkillSuggestionRow(**row_to_dict(db_row)))

    return SkillSnapshot(
        id=snapshot_id,
        input_fp=header["input_fp"],
        resume_fp=header["resume_fp"],
        corpus_size=header["corpus_size"],
        selection_rule=header["selection_rule"],
        created_at=header["created_at"],
        vacancy_ids=header["vacancy_ids"],
        rows=saved_rows,
    )


class SkillsPanel(BaseModel):
    """Ответ `GET /api/resume/skills`: снимок + флаг устаревания. Только чтение — не
    вызывает LLM. Пересборка — отдельно, через `refresh_snapshot`."""

    rows: list[SkillSuggestionRow] = Field(default_factory=list)
    stale: bool = False
    stale_reason: str = ""
    selection_rule: str = ""
    corpus_size: int = 0
    slots_used: int = 0
    slots_limit: int = HH_KEY_SKILLS_LIMIT
    created_at: datetime | None = None


class SkillStateUpdate(BaseModel):
    """`PATCH /api/resume/skills` — «скрыть» / «вернуть» одно предложение (Решение 6)."""

    skill: str = Field(min_length=1)
    user_state: UserState


async def load_skills_panel(*, account_id: int, db: Executor | None = None) -> SkillsPanel:
    """Снимок аккаунта запроса для GET: сохранённые строки + дешёвые детерминированные числа
    выборки.

    Никогда не вызывает LLM — пересборка только через `refresh_snapshot` (руками) или
    фоновые триггеры E-02 (`maybe_auto_refresh_for_new_vacancies`/`_for_resume_change`). `stale`
    покрывает три случая: вакансий выборки нет, снимка ещё не было, вход изменился с последней
    сборки — в третьем случае причина названа точно («+N новых вакансий» либо «резюме
    изменилось»), а не общей фразой.
    """
    db = db or get_pool()
    data = await read_resume_data_for_account(account_id, db=db)
    key_skills = [s for s in (data.key_skills or []) if s and s.strip()]
    selection = await load_selection_corpus(account_id=account_id, data=data, db=db)
    selection_rule = await describe_selection(account_id=account_id, data=data, db=db)
    snapshot = await load_latest_snapshot(account_id=account_id, db=db)

    if not selection:
        stale, reason = True, "нет вакансий выборки"
    elif snapshot is None:
        stale, reason = True, "снимок ещё не собран — нажми «Пересобрать»"
    else:
        current_fp = _input_fingerprint(key_skills, selection)
        stale = current_fp != snapshot.input_fp
        if not stale:
            reason = ""
        else:
            new_count = count_new_vacancies(snapshot, selection)
            if new_count > 0:
                reason = (
                    f"+{new_count} {plural_vacancies(new_count)} с последнего разбора — "
                    "нажми «Пересобрать»"
                )
            else:
                reason = "резюме изменилось с последнего разбора — нажми «Пересобрать»"

    return SkillsPanel(
        rows=snapshot.rows if snapshot else [],
        stale=stale,
        stale_reason=reason,
        selection_rule=selection_rule,
        corpus_size=len(selection),
        slots_used=len(key_skills),
        created_at=snapshot.created_at if snapshot else None,
    )


async def refresh_snapshot(
    *, account_id: int, db: Executor | None = None, llm: ports.LlmPort | None = None
) -> SkillSnapshot:
    """Пересобрать и сохранить снимок аккаунта запроса целиком.

    Двойной клик по «Пересобрать» / две вкладки одного аккаунта → один прогон: обёрнуто в
    single-flight по ключу, включающему `account_id`
    (plans/multitenancy_gaps_2026_08_06.md §3.1 п.6/§4.3) — раньше ключ был фиксированной
    строкой на всю инсталляцию, и одновременная пересборка двух аккаунтов склеилась бы в одну:
    один пользователь получил бы снимок другого.
    """
    from core.platform.cache.single_flight import get_single_flight

    async def _run() -> SkillSnapshot:
        snapshot = await build_snapshot(account_id=account_id, db=db, llm=llm)
        return await save_snapshot(snapshot, account_id=account_id, db=db)

    return await get_single_flight().do(f"resume_skill_suggest_refresh:{account_id}", _run)


async def maybe_auto_refresh_for_new_vacancies(
    *, account_id: int, db: Executor | None = None, llm: ports.LlmPort | None = None
) -> bool:
    """Порог 1 (Решение 2): вызывать из подписки на `VacancyScored`.

    Считает, сколько вакансий текущей выборки не входили в последний снимок; при
    `>= SETTING_KEY_NEW_VACANCIES_THRESHOLD` и соблюдённой нижней границе
    (`SETTING_KEY_MIN_REFRESH_INTERVAL_HOURS`) пересобирает снимок в фоне. Пустая выборка —
    нечего копить, выходит сразу. Возвращает, была ли запущена пересборка (для теста/лога).
    """
    db = db or get_pool()
    data = await read_resume_data_for_account(account_id, db=db)
    selection = await load_selection_corpus(account_id=account_id, data=data, db=db)
    if not selection:
        return False
    previous = await load_latest_snapshot(account_id=account_id, db=db)
    threshold = await _load_new_vacancies_threshold(account_id=account_id, db=db)
    if count_new_vacancies(previous, selection) < threshold:
        return False
    min_interval_hours = await _load_min_refresh_interval_hours(account_id=account_id, db=db)
    if not _min_interval_elapsed(previous, min_interval_hours=min_interval_hours):
        return False
    await refresh_snapshot(account_id=account_id, db=db, llm=llm)
    return True


async def maybe_auto_refresh_for_resume_change(
    *, account_id: int, db: Executor | None = None, llm: ports.LlmPort | None = None
) -> bool:
    """Порог 2 (Решение 2): вызывать из подписки на `ResumeUpdated`.

    Пересобирает, только если `resume_skills_fingerprint` сдвинулся с последнего снимка —
    правка телефона/образования/языков его не двигает и пересборку не тратит. Нижняя граница
    (`SETTING_KEY_MIN_REFRESH_INTERVAL_HOURS`) действует и здесь: серия быстрых автосейвов формы
    не должна давать серию LLM-вызовов.
    """
    db = db or get_pool()
    data = await read_resume_data_for_account(account_id, db=db)
    selection = await load_selection_corpus(account_id=account_id, data=data, db=db)
    if not selection:
        return False
    previous = await load_latest_snapshot(account_id=account_id, db=db)
    current_fp = resume_skills_fingerprint(data)
    if previous is not None and previous.resume_fp == current_fp:
        return False
    min_interval_hours = await _load_min_refresh_interval_hours(account_id=account_id, db=db)
    if not _min_interval_elapsed(previous, min_interval_hours=min_interval_hours):
        return False
    await refresh_snapshot(account_id=account_id, db=db, llm=llm)
    return True


async def set_user_state(
    skill: str, user_state: UserState, *, account_id: int, db: Executor | None = None
) -> SkillSuggestionRow | None:
    """«Скрыть» / «вернуть» одну строку последнего снимка аккаунта запроса по канону имени
    (Решение 6).

    `None` — снимков ещё не было или навык не найден в последнем снимке (роутер отвечает 404).
    """
    db = db or get_pool()
    header = await db.fetchrow(
        "select id from resume_skill_snapshots where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    if header is None:
        return None
    key = _canon_key(skill)
    rows = await db.fetch(
        "select id, skill from resume_skill_suggestions where snapshot_id = $1", header["id"]
    )
    target_id = next((r["id"] for r in rows if _canon_key(r["skill"]) == key), None)
    if target_id is None:
        return None
    row = await db.fetchrow(
        "update resume_skill_suggestions set user_state = $2, state_at = now() "
        "where id = $1 "
        "returning skill, state, renames_to, importance, demand_count, demand_total, "
        "companies, rationale, user_state, state_at",
        target_id,
        user_state,
    )
    assert row is not None
    return SkillSuggestionRow(**row_to_dict(row))


__all__ = [
    "DEFAULT_MIN_REFRESH_INTERVAL_HOURS",
    "DEFAULT_NEW_VACANCIES_THRESHOLD",
    "FEATURE",
    "MAX_ACTIONS",
    "SETTING_KEY_MIN_REFRESH_INTERVAL_HOURS",
    "SETTING_KEY_NEW_VACANCIES_THRESHOLD",
    "SkillActionLlm",
    "SkillDemand",
    "SkillSnapshot",
    "SkillStateUpdate",
    "SkillSuggestLlm",
    "SkillSuggestionRow",
    "SkillsPanel",
    "build_demand",
    "build_snapshot",
    "clamp_actions",
    "count_new_vacancies",
    "load_latest_snapshot",
    "load_skills_panel",
    "maybe_auto_refresh_for_new_vacancies",
    "maybe_auto_refresh_for_resume_change",
    "refresh_snapshot",
    "resume_skills_fingerprint",
    "save_snapshot",
    "set_user_state",
]
