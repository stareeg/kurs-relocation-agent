"""Единый пайплайн «Подогнать под ATS» (FR2-32/33).

Вход: всё резюме + разрывы по требованиям выборки (снимок навыков S-04,
`core.domains.profile.skill_suggest`) + фрагменты топ-N проскоренных вакансий
(`load_top_scored_jobs`). Раньше сюда шёл `report.missing` — n-граммный gap-отчёт,
тот же источник, что давал «локация 90 %» в чипах; теперь разрывы берутся
из того же извлечённого по требованиям снимка. Выход — не одна гигантская схема (см.
situation.py / docs/problems.md про `400 Schema is too complex`), а параллельные малые вызовы:

- на каждый блок опыта — `strengthen_section` (refine) → переписанный `description`;
- «Обо мне» — `strengthen_section` (rewrite).

Навыки пайплайн больше не предлагает сам: снимок навыков уже
даёт add/drop/rename по тем же разрывам с реальным спросом и каноном имён, отдельный
LLM-вызов дублировал его же вход (`gaps` ниже) без числовых доказательств — предложения по
навыкам живут только в `SkillsPanel`.

FR2-33: пустые/почти пустые блоки (только шапка) → `skipped` с человекочитаемой причиной,
без LLM и без выдуманного опыта. Промпты: реюз `prompts/profile/strengthen*`. Ничего не
сохраняет — UI принимает правки.
"""

# Строки системного промпта — связная проза; перенос на 100 символов вставлял бы разрывы.
# ruff: noqa: E501

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.profile.context import StrengthenContext, gather_bio_material
from core.domains.profile.gap import load_top_scored_jobs
from core.domains.profile.model import ResumeData
from core.domains.profile.strengthen import StrengthenResult, strengthen_section
from core.domains.profile.structured_store import read_resume_data_for_account
from core.kernel.errors import LlmError
from core.platform.observability import event

if TYPE_CHECKING:
    # Ленивый рантайм-импорт в build_ats_fit_context — skill_suggest.py сам импортирует
    # HH_KEY_SKILLS_LIMIT отсюда, top-level импорт зациклил бы модули друг на друге.
    from core.domains.profile.skill_suggest import SkillSnapshot
    from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

# hh.ru физически режет ключевые навыки на 30 тегов — канон с фронта и gap.py.
HH_KEY_SKILLS_LIMIT = 30

# Минимальная длина описания опыта для refine (как в strengthen_section).
MIN_BLOCK_CHARS = 30

# Фрагмент вакансии в контекст — достаточно требований, не тащим весь текст.
_VACANCY_FRAGMENT_CHARS = 600

# Человекочитаемые причины skip (канон FR2-33 — UI/тесты сверяют точные строки).
SKIP_REASON_EXPERIENCE_EMPTY = "опыт не заполнен — подгонять нечего"
SKIP_REASON_ABOUT_NO_BODY = "в резюме мало содержимого — сначала заполни опыт или навыки"

# Плейсхолдеры «почти пусто» (новый пользователь / заглушка в форме).
_PLACEHOLDER_ONLY_RE = re.compile(r"^[\s.·•\-–—_*…/\\]+$", re.UNICODE)
_THIN_PLACEHOLDERS = frozenset(
    {
        "описание",
        "обязанности",
        "tba",
        "todo",
        "n/a",
        "na",
        "нет",
        "пусто",
        "...",
        "…",
        "text",
        "lorem",
        "placeholder",
    }
)


class AtsFitExperiencePatch(BaseModel):
    """Правка одного блока опыта (индекс в `ResumeData.experience`)."""

    index: int = Field(description="Индекс в experience[]")
    company: str = ""
    position: str = ""
    original: str = Field(description="Текущий description")
    proposed: str = Field(default="", description="Переписанный description (пусто при skip/error)")
    status: Literal["ok", "skipped", "error"] = "ok"
    skip_reason: str | None = None
    error: str | None = None


class AtsFitAboutPatch(BaseModel):
    """Правка блока «Обо мне»."""

    original: str = ""
    proposed: str = ""
    status: Literal["ok", "skipped", "error"] = "ok"
    skip_reason: str | None = None
    error: str | None = None


class AtsFitResult(BaseModel):
    """Сводка пайплайна ats-fit для UI (разложит по форме)."""

    experience: list[AtsFitExperiencePatch] = Field(default_factory=list)
    about: AtsFitAboutPatch = Field(default_factory=AtsFitAboutPatch)
    missing_concepts: list[str] = Field(
        default_factory=list,
        description="Навыки-разрывы (state=add) из снимка S-04, которые шли во вход пайплайна",
    )
    top_jobs_count: int = Field(
        default=0, description="Сколько фрагментов топ-вакансий реально попало в контекст"
    )
    has_market: bool = Field(
        default=False,
        description="Были ли проскоренные вакансии / gap-корпус (для плашки FR2-37)",
    )


def is_block_too_thin(text: str, *, min_chars: int = MIN_BLOCK_CHARS) -> bool:
    """Пустой / почти пустой блок: короче порога, одни точки/тире или явный плейсхолдер."""
    cleaned = (text or "").strip()
    if len(cleaned) < min_chars:
        return True
    if _PLACEHOLDER_ONLY_RE.match(cleaned):
        return True
    return cleaned.casefold() in _THIN_PLACEHOLDERS


def has_substantive_resume_body(data: ResumeData) -> bool:
    """Есть ли из чего писать «Обо мне» без выдумок: опыт с текстом или key_skills.

    Одна шапка (должность/зарплата) — не считается: rewrite иначе сочинит биографию.
    """
    for exp in data.experience or []:
        if not is_block_too_thin(exp.description or ""):
            return True
    return any(s.strip() for s in (data.key_skills or []) if s)


def skip_experience_if_thin(
    index: int,
    company: str,
    position: str,
    original: str,
) -> AtsFitExperiencePatch | None:
    """FR2-33: тонкий description → skipped-маркер; иначе None (можно звать LLM)."""
    if not is_block_too_thin(original):
        return None
    return AtsFitExperiencePatch(
        index=index,
        company=company or "",
        position=position or "",
        original=original or "",
        status="skipped",
        skip_reason=SKIP_REASON_EXPERIENCE_EMPTY,
    )


def skip_about_if_no_body(original: str, data: ResumeData) -> AtsFitAboutPatch | None:
    """FR2-33: только шапка / пустой материал → skipped, без rewrite-выдумок."""
    if has_substantive_resume_body(data):
        return None
    return AtsFitAboutPatch(
        original=original or "",
        status="skipped",
        skip_reason=SKIP_REASON_ABOUT_NO_BODY,
    )


def _format_gap_names(snapshot: SkillSnapshot | None, limit: int = 15) -> list[str]:
    """Топ навыков-разрывов снимка (state=add) — требует выборка, в резюме нет.

    `rename`/`drop`/`have` сюда не попадают: это не «чего не хватает», это готовая правка
    существующего тега или опора, которую нечего добавлять.
    """
    if snapshot is None:
        return []
    return [row.skill for row in snapshot.rows if row.state == "add" and row.skill][:limit]


def _format_job_fragments(texts: list[str], fragment_chars: int = _VACANCY_FRAGMENT_CHARS) -> str:
    """Фрагменты топ-N vacancy_text для контекста (не полный текст)."""
    if not texts:
        return ""
    lines: list[str] = []
    for i, raw in enumerate(texts, start=1):
        text = (raw or "").strip()
        if not text:
            continue
        snippet = text[:fragment_chars].replace("\n", " ")
        if len(text) > fragment_chars:
            snippet += "…"
        lines.append(f"{i}. {snippet}")
    if not lines:
        return ""
    return (
        f"Фрагменты топ-{len(lines)} проскоренных вакансий (под них точим резюме):\n"
        + "\n".join(lines)
        + "\n"
    )


def _format_gap_block(names: list[str], corpus_size: int) -> str:
    if not names:
        return "Разрывов по требованиям выборки не найдено — рынок покрыт.\n"
    lines = [f"- {n}" for n in names]
    return (
        "Разрывы по требованиям выборки "
        f"(топ-{len(names)} по спросу, корпус {corpus_size} вакансий):\n" + "\n".join(lines) + "\n"
    )


async def build_ats_fit_context(
    *,
    account_id: int,
    data: ResumeData | None = None,
    snapshot: SkillSnapshot | None = None,
    top_jobs_texts: list[str] | None = None,
    db: Executor | None = None,
) -> tuple[StrengthenContext, list[str], int, bool]:
    """Собрать общий контекст аккаунта запроса один раз на весь пайплайн.

    Возвращает (ctx, gap_names, top_jobs_count, has_market).
    Топ-вакансии — строго через `load_top_scored_jobs` (канон FR2-32), не list_jobs.

    Разрывы — из снимка навыков, не из n-граммного gap-отчёта: `report.missing` —
    тот же корпусный мусор, что раньше шёл в чипы «локация 90 %», и он засорял
    вход этого пайплайна тоже.
    """
    settings = get_settings()
    if data is None:
        data = await read_resume_data_for_account(account_id, db=db)
    if snapshot is None:
        from core.domains.profile.skill_suggest import load_latest_snapshot

        try:
            snapshot = await load_latest_snapshot(account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001 — нет PG → без снимка, пайплайн жив
            logger.debug("ats-fit: снимок навыков недоступен: %s", exc)
            snapshot = None

    top_n = int(getattr(settings, "resume_ats_fit_top_vacancies", 0) or 0)
    if top_n <= 0:
        top_n = int(getattr(settings, "resume_strengthen_top_vacancies", 5) or 5)
    if top_jobs_texts is None:
        try:
            top_jobs_texts = await load_top_scored_jobs(top_n, account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ats-fit: топ-N вакансий недоступен: %s", exc)
            top_jobs_texts = []

    gaps = _format_gap_names(snapshot)
    corpus_size = int(snapshot.corpus_size) if snapshot is not None else 0
    vac_block = _format_job_fragments(top_jobs_texts or [])
    # FR2-37: без снимка/топ-вакансий не подмешиваем «рыночный» текст
    # (в т.ч. ложное «рынок покрыт» при отсутствующем снимке).
    has_market = bool(gaps) or bool(top_jobs_texts) or snapshot is not None
    parts: list[str] = []
    if snapshot is not None:
        parts.append(_format_gap_block(gaps, corpus_size))
    if vac_block:
        parts.append(vac_block)
    text = "\n".join(parts).strip()
    bio = gather_bio_material(data)
    ctx = StrengthenContext(
        text=text,
        has_gap=snapshot is not None,
        has_funnel=False,
        has_top_vacancies=bool(top_jobs_texts),
        bio_material=bio,
    )
    return ctx, gaps, len(top_jobs_texts or []), has_market


def assemble_ats_fit_result(
    *,
    experience: list[AtsFitExperiencePatch],
    about: AtsFitAboutPatch,
    missing_concepts: list[str],
    top_jobs_count: int,
    has_market: bool,
) -> AtsFitResult:
    """Сборка итога из частичных ответов (для тестов и FR2-38: один блок упал — остальные живы)."""
    return AtsFitResult(
        experience=experience,
        about=about,
        missing_concepts=list(missing_concepts),
        top_jobs_count=top_jobs_count,
        has_market=has_market,
    )


async def _rewrite_experience(
    index: int,
    company: str,
    position: str,
    original: str,
    *,
    account_id: int,
    role_title: str,
    keep_terms: list[str],
    ctx: StrengthenContext,
) -> AtsFitExperiencePatch:
    skipped = skip_experience_if_thin(index, company, position, original)
    if skipped is not None:
        return skipped
    text = (original or "").strip()
    try:
        result: StrengthenResult = await strengthen_section(
            "experience",
            text,
            account_id=account_id,
            role_title=role_title,
            keep_terms=keep_terms,
            mode="refine",
            ctx=ctx,
        )
        return AtsFitExperiencePatch(
            index=index,
            company=company,
            position=position,
            original=original or "",
            proposed=result.text,
            status="ok",
        )
    except Exception as exc:  # noqa: BLE001 — частичный сбой не валит весь пайплайн
        logger.warning("ats-fit: опыт[%s] упал: %s", index, exc)
        return AtsFitExperiencePatch(
            index=index,
            company=company,
            position=position,
            original=original or "",
            status="error",
            error=str(exc),
        )


async def _rewrite_about(
    original: str,
    *,
    account_id: int,
    data: ResumeData,
    role_title: str,
    keep_terms: list[str],
    ctx: StrengthenContext,
) -> AtsFitAboutPatch:
    skipped = skip_about_if_no_body(original, data)
    if skipped is not None:
        return skipped
    if not ctx.bio_material:
        return AtsFitAboutPatch(
            original=original or "",
            status="skipped",
            skip_reason=SKIP_REASON_ABOUT_NO_BODY,
        )
    try:
        result = await strengthen_section(
            "about",
            original or "",
            account_id=account_id,
            role_title=role_title,
            keep_terms=keep_terms,
            mode="rewrite",
            ctx=ctx,
        )
        return AtsFitAboutPatch(
            original=original or "",
            proposed=result.text,
            status="ok",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ats-fit: about упал: %s", exc)
        return AtsFitAboutPatch(
            original=original or "",
            status="error",
            error=str(exc),
        )


async def strengthen_experience_block(
    *, index: int, account_id: int, db: Executor | None = None
) -> AtsFitExperiencePatch:
    """Усилить одно место работы под ATS (кнопка «Подогнать под ATS» у конкретного описания).

    В отличие от полного `iter_ats_fit_events`, переписывает только один блок опыта. Контекст
    собирается тот же скромный (снимок навыков + фрагменты топ-вакансий, без полных текстов
    воронки), чтобы LLM понимала запрос рынка, но промпт не раздувался.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    data = await read_resume_data_for_account(account_id, db=db)
    experience = list(data.experience or [])
    if not (0 <= index < len(experience)):
        raise ValueError(f"блок опыта с индексом {index} не найден")

    ctx, _gaps, _count, _has_market = await build_ats_fit_context(
        account_id=account_id, data=data, db=db
    )
    role_title = (data.position.title or "").strip()
    keep_terms = [s.strip() for s in (data.key_skills or []) if s and s.strip()]

    exp = experience[index]
    return await _rewrite_experience(
        index,
        exp.company or "",
        exp.position or "",
        exp.description or "",
        account_id=account_id,
        role_title=role_title,
        keep_terms=keep_terms,
        ctx=ctx,
    )


async def strengthen_about_block(
    *, account_id: int, db: Executor | None = None
) -> AtsFitAboutPatch:
    """Усилить блок «Обо мне» под ATS (кнопка «Подогнать под ATS» над блоком «Обо мне»)."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    data = await read_resume_data_for_account(account_id, db=db)
    ctx, _gaps, _count, _has_market = await build_ats_fit_context(
        account_id=account_id, data=data, db=db
    )
    role_title = (data.position.title or "").strip()
    keep_terms = [s.strip() for s in (data.key_skills or []) if s and s.strip()]

    return await _rewrite_about(
        data.about or "",
        account_id=account_id,
        data=data,
        role_title=role_title,
        keep_terms=keep_terms,
        ctx=ctx,
    )


async def iter_ats_fit_events(*, account_id: int, db: Executor | None = None):
    """FR2-38: параллельный пайплайн с событиями прогресса (→ Pipeline).

    Yields dict:
      - ``{"type":"start","done":0,"total":K}``
      - ``{"type":"progress","done":n,"total":K,"label":"..."}``
      - ``{"type":"result","data": <AtsFitResult dict>}``

    Дневных cost-лимитов нет (сняты, лимит трат — на стороне OpenRouter); внутри LLM-вызовов
    остаётся только preflight-гард размера запроса (`LLM_MAX_INPUT_CHARS`, OpenRouterChatModel).
    Частичный сбой блока → status=error у блока, остальные живы.
    """
    from core.app.pipeline import Pipeline, Step

    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    data = await read_resume_data_for_account(account_id, db=db)
    ctx, gaps, top_jobs_count, has_market = await build_ats_fit_context(
        account_id=account_id, data=data, db=db
    )

    role_title = (data.position.title or "").strip()
    keep_terms = [s.strip() for s in (data.key_skills or []) if s and s.strip()]
    experience_src = list(data.experience or [])

    labels: dict[str, str] = {"about": "Обо мне"}
    steps: list[Step] = [
        Step(
            "about",
            lambda _c: _rewrite_about(
                data.about or "",
                account_id=account_id,
                data=data,
                role_title=role_title,
                keep_terms=keep_terms,
                ctx=ctx,
            ),
        ),
    ]
    for i, e in enumerate(experience_src):
        name = f"exp_{i}"
        who = " · ".join(p for p in (e.company or "", e.position or "") if p) or f"Опыт #{i + 1}"
        labels[name] = who
        steps.append(
            Step(
                name,
                lambda _c, idx=i, exp=e: _rewrite_experience(
                    idx,
                    exp.company or "",
                    exp.position or "",
                    exp.description or "",
                    account_id=account_id,
                    role_title=role_title,
                    keep_terms=keep_terms,
                    ctx=ctx,
                ),
            )
        )

    total = len(steps)
    yield {"type": "start", "done": 0, "total": total, "label": ""}

    about: AtsFitAboutPatch | None = None
    experience: list[AtsFitExperiencePatch | None] = [None] * len(experience_src)
    done_count = 0

    async for pipeline_event in Pipeline(steps, name="ats_fit").stream():
        if pipeline_event.type != "step_done":
            continue
        done_count += 1
        payload = pipeline_event.data
        if pipeline_event.step == "about":
            about = payload  # type: ignore[assignment]
        elif pipeline_event.step.startswith("exp_"):
            index = int(pipeline_event.step.split("_", 1)[1])
            experience[index] = payload  # type: ignore[assignment]
        yield {
            "type": "progress",
            "done": done_count,
            "total": total,
            "label": labels.get(pipeline_event.step, pipeline_event.step),
        }

    result = assemble_ats_fit_result(
        experience=[p for p in experience if p is not None],
        about=about or AtsFitAboutPatch(),
        missing_concepts=gaps,
        top_jobs_count=top_jobs_count,
        has_market=has_market,
    )
    error_n = sum(1 for p in result.experience if p.status == "error") + (
        1 if result.about.status == "error" else 0
    )
    skipped_n = sum(1 for p in result.experience if p.status == "skipped") + (
        1 if result.about.status == "skipped" else 0
    )
    event(
        logger,
        "LLM",
        "ats_fit: %d блоков, пропущено=%d, ошибок=%d",
        total,
        skipped_n,
        error_n,
        total=total,
        skipped=skipped_n,
        errors=error_n,
        missing_concepts=len(gaps),
        level=logging.WARNING if error_n else logging.INFO,
    )
    yield {"type": "result", "data": result.model_dump(mode="json")}


__all__ = [
    "HH_KEY_SKILLS_LIMIT",
    "MIN_BLOCK_CHARS",
    "SKIP_REASON_ABOUT_NO_BODY",
    "SKIP_REASON_EXPERIENCE_EMPTY",
    "AtsFitAboutPatch",
    "AtsFitExperiencePatch",
    "AtsFitResult",
    "assemble_ats_fit_result",
    "build_ats_fit_context",
    "iter_ats_fit_events",
    "strengthen_about_block",
    "strengthen_experience_block",
    "has_substantive_resume_body",
    "is_block_too_thin",
    "skip_about_if_no_body",
    "skip_experience_if_thin",
]
