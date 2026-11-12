"""Усиление блока резюме через critique-loop (JS-resume-strengthen-v2).

Пайплайн из 3 шагов (модели — только тиры LlmFeature / реестр):
1. **Draft** — агент `resume_strengthen` (reserve-тир) переписывает блок с rich-контекстом.
2. **Critique** — агент `resume_strengthen_critic` (reserve-тир), structured CritiqueResult.
3. **Finetune** — снова `resume_strengthen`, на входе исходник + черновик + критика.

Два режима (`mode`):
- `refine` (по умолчанию): исходный текст блока подаётся в LLM — та переписывает его.
- `rewrite`: исходный текст НЕ подаём (LLM не ленится на переформулировке). Вместо него
  в draft идёт фактический био-материал резюме (должность/навыки/опыт) + контекст рынка.
  Под «Обо мне» — пишет с нуля по материалу резюме. Critique/finetune тоже без исходника.

Если critique упал — final = draft (single). Промпты в `prompts/profile/`. Не сохраняет —
владелец ревьюит и принимает в форме.
"""

# Строки системного промпта — связная проза; перенос на 100 символов вставлял бы разрывы.
# ruff: noqa: E501

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.config import get_settings
from core.domains.profile.bullet_format import ensure_bullet_format
from core.domains.profile.context import StrengthenContext, build_strengthen_context
from core.domains.profile.model import ResumeData
from core.domains.profile.strengthen_quality import (
    COSMETIC_SIMILARITY_THRESHOLD,
    build_cosmetic_repair_user,
    format_enhancement_directive,
    is_substantive_enhancement,
    lint_strengthen_text,
)
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.text.style_lint import StyleIssue
from core.platform.observability import event

# Имена агентов = ключи реестра LlmFeature / колонка llm_usage (без прямого слага модели).
_STRENGTHEN_AGENT = "resume_strengthen"
_CRITIC_AGENT = "resume_strengthen_critic"

logger = logging.getLogger(__name__)

_KIND_HINT: dict[str, str] = {
    "experience": (
        "Это описание места работы в резюме - что человек делал, какие системы строил, "
        "за что отвечал, какой дал результат. Покажи ЧТО делал, без объяснений «зачем нужно»."
    ),
    "about": (
        "Это блок «Обо мне» - короткая самопрезентация. Кратко и ёмко: ключевой опыт, "
        "чем силён, что ищет. Без воды и обрамления. Первые 4 строки - под ATS-скрининг."
    ),
}


class CritiqueIssue(BaseModel):
    """Одно замечание критика к черновику."""

    location: str = Field(description="Где проблема: цитата или номер строки / секция")
    problem: str = Field(description="Что не так")
    fix: str = Field(description="Как исправить одной строкой")


class CritiqueResult(BaseModel):
    """Structured-ответ критика (шаг 2)."""

    issues: list[CritiqueIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(
        default_factory=list,
        description="Готовые правки одной строкой каждая (что заменить в черновике)",
    )
    verdict: Literal["ok", "needs_work", "rewrite"] = Field(
        description="ok — можно отдавать, needs_work — точечные правки, rewrite — переделать"
    )


class StrengthenResult(BaseModel):
    """Финал пайплайна: текст-кандидат + следы промежуточных шагов для UI."""

    text: str = Field(description="Финальный переписанный текст блока")
    draft: str | None = Field(default=None, description="Черновик шага 1 (для показа «как было»)")
    critique: CritiqueResult | None = Field(
        default=None, description="Критика шага 2 (если был); None — critique-loop пропущен"
    )
    pipeline: str = Field(
        default="single",
        description="critique_loop | single — был ли полноценный ансамбль или fallback",
    )


@lru_cache(maxsize=1)
def _load_prompt_template(path_str: str) -> str:
    """Сырой текст файла-промпта — кэш по пути, диск не перечитываем на каждый вызов."""
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Промпт не найден: {path} (CWD={Path.cwd()}). Проверь путь в core.domains.profile.llm."
        )
    return path.read_text(encoding="utf-8")


def _load_prompt(path_str: str, *, data: ResumeData) -> str:
    """Промпт с подставленным `{{CANDIDATE_IDENTITY}}` — идентичность не кэшируем внутри
    `_load_prompt_template`, иначе правка резюме не подхватится без рестарта процесса."""
    from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity

    identity = load_candidate_identity(data=data)
    return _load_prompt_template(path_str).replace(CANDIDATE_IDENTITY_TOKEN, identity)


def _build_user_prompt(
    kind: str,
    text: str,
    role_title: str,
    keep_terms: list[str],
    ctx: StrengthenContext,
) -> str:
    hint = _KIND_HINT.get(kind, _KIND_HINT["experience"])
    role = f"\nРоль кандидата: {role_title}." if role_title else ""
    terms = ""
    if keep_terms:
        terms = (
            "\n\nОбязательно сохрани эти термины (ATS-ключи), если они есть в тексте:\n"
            + ", ".join(keep_terms)
        )
    context_block = ""
    if ctx.text:
        context_block = (
            f"\n\n## Контекст рынка и аналитики (используй для усиления)\n\n{ctx.text}\n"
        )
    return f"""{hint}{role}

## Исходный текст блока

{text}
{terms}{context_block}

Перепиши этот блок по правилам выше. Это **усиление** под целевой грейд и критерии слева —
добавь масштаб, задачи и результаты, а не косметический пересказ. Верни только переписанный текст."""


def _build_rewrite_user_prompt(
    kind: str,
    role_title: str,
    keep_terms: list[str],
    ctx: StrengthenContext,
) -> str:
    """User-промпт для rewrite-режима: исходный текст блока НЕ подаём (LLM не ленится на
    переформулировке). Вместо него — фактический био-материал резюме + контекст рынка/топ-вакансий.
    """
    hint = _KIND_HINT.get(kind, _KIND_HINT["experience"])
    role = f"\nРоль кандидата: {role_title}." if role_title else ""
    terms = ""
    if keep_terms:
        terms = (
            "\n\nATS-ключи, которые должны попасть в текст (если они есть в материале ниже):\n"
            + ", ".join(keep_terms)
        )
    bio_block = ""
    if ctx.bio_material:
        bio_block = (
            f"\n\n## Биографические якоря из резюме (компании, роли, стек)\n\n{ctx.bio_material}\n"
        )
    context_block = ""
    if ctx.text:
        context_block = (
            f"\n\n## Контекст рынка и аналитики (подстраивайся под спрос)\n\n{ctx.text}\n"
        )
    return f"""{hint}{role}{bio_block}{context_block}{terms}

Напиши этот блок с нуля по правилам выше. Якоря биографии (компании, роли, стек) сохрани;
обязанности и достижения **усили** под целевой грейд и критерии слева — не пересказывай
слабые формулировки один в один. Верни только текст блока."""


def _build_critic_prompt(
    kind: str,
    role_title: str,
    keep_terms: list[str],
    original: str,
    draft: str,
    ctx: StrengthenContext,
) -> str:
    hint = _KIND_HINT.get(kind, _KIND_HINT["experience"])
    role = f"\nРоль кандидата: {role_title}." if role_title else ""
    terms = (
        "\nATS-ключи, которые должны сохраниться:\n" + ", ".join(keep_terms) if keep_terms else ""
    )
    context_block = ""
    if ctx.text:
        context_block = (
            f"\n\n## Контекст рынка (для проверки релевантности критики)\n\n{ctx.text}\n"
        )
    # В rewrite-режиме исходника нет — критикуем черновик против якорей резюме + стиля.
    # Усиление задач/метрик под грейд — норма; якоря (компания/роль) не трогаем.
    if original:
        source_block = f"\n\n## Исходный текст блока\n\n{original}\n\n## Черновик усиления (его критикуем)\n\n{draft}\n"
    else:
        bio = (
            f"\n\n## Биографические якоря резюме (компании/роли; усиление под рынок допустимо)\n\n{ctx.bio_material}\n"
            if ctx.bio_material
            else ""
        )
        source_block = f"{bio}\n\n## Черновик (его критикуем, исходного текста нет — писали с нуля)\n\n{draft}\n"
    return f"""{hint}{role}{terms}{context_block}{source_block}

Разбери черновик по правилам из system-промпта. Верни строго JSON по схеме."""


def _build_finetune_prompt(
    kind: str,
    role_title: str,
    original: str,
    draft: str,
    critique: CritiqueResult,
    ctx: StrengthenContext,
) -> str:
    hint = _KIND_HINT.get(kind, _KIND_HINT["experience"])
    role = f"\nРоль кандидата: {role_title}." if role_title else ""
    critique_text = _render_critique(critique)
    context_block = ""
    if ctx.text:
        context_block = f"\n\n## Контекст рынка (для финальной правки)\n\n{ctx.text}\n"
    # В rewrite-режиме исходника нет — финал собираем из черновика + критики + (опционально) bio.
    if original:
        source_block = (
            f"\n\n## Исходный текст блока\n\n{original}\n\n## Черновик усиления\n\n{draft}\n"
        )
    else:
        bio = (
            f"\n\n## Фактический материал резюме (если нужно вернуть потерянные факты)\n\n{ctx.bio_material}\n"
            if ctx.bio_material
            else ""
        )
        source_block = f"{bio}\n\n## Черновик (написан с нуля)\n\n{draft}\n"
    return f"""{hint}{role}{context_block}{source_block}

## Критика вторым моделью

{critique_text}

Собери финальный вариант: возьми лучшее из черновика, примени верную критику, сохрани всё ценное.
Верни только финальный текст блока."""


def _render_critique(critique: CritiqueResult) -> str:
    """Текстовое представление критики для finetune-промпта."""
    parts: list[str] = [f"Вердикт: {critique.verdict}"]
    if critique.issues:
        parts.append("Замечания:")
        for i, issue in enumerate(critique.issues, start=1):
            parts.append(f"{i}. [{issue.location}] {issue.problem} → {issue.fix}")
    if critique.suggestions:
        parts.append("Готовые правки:")
        for s in critique.suggestions:
            parts.append(f"- {s}")
    if not critique.issues and not critique.suggestions:
        parts.append("Существенных замечаний нет.")
    return "\n".join(parts)


def _strip_codefence(raw: str) -> str:
    out = raw.strip()
    if out.startswith("```"):
        out = out.strip("`").strip()
        # Срезаем возможный язык после ```
        if out.lower().startswith(("markdown", "text", "json")):
            first_nl = out.find("\n")
            if first_nl != -1:
                out = out[first_nl:].strip()
    return out


def _normalize_block_output(text: str, *, kind: str) -> str:
    """LLM иногда отдаёт prose или нумерацию — приводим к `- …` для парсера балла."""
    return ensure_bullet_format(text, kind=kind)


def _log_style_issues(issues: Sequence[StyleIssue], *, kind: str, mode: str) -> None:
    if not issues:
        return
    sample = "; ".join(f"{i.code}: {i.message}" for i in issues[:3])
    logger.info(
        "strengthen %s/%s: style_lint %d замечаний (%s)",
        kind,
        mode,
        len(issues),
        sample,
    )


async def _apply_output_guards(
    text: str,
    *,
    kind: str,
    mode: str,
    original: str,
    keep_terms: list[str],
    data: ResumeData,
    finetune_prompt: str,
    role_title: str,
    pipeline: str,
) -> tuple[str, str]:
    """Bullet-format, style_lint, repair косметического пересказа (refine)."""
    out = _normalize_block_output(text, kind=kind)
    _log_style_issues(lint_strengthen_text(out, keep_terms), kind=kind, mode=mode)

    if mode != "refine" or not (original or "").strip():
        return out, pipeline

    if is_substantive_enhancement(original, out):
        return out, pipeline

    logger.warning(
        "strengthen %s/%s: косметический пересказ (jaccard≥%.2f), repair-вызов",
        kind,
        mode,
        COSMETIC_SIMILARITY_THRESHOLD,
    )
    repair_user = build_cosmetic_repair_user(
        kind=kind,
        original=original.strip(),
        proposed=out,
        role_title=role_title,
        enhancement_block=format_enhancement_directive(data),
    )
    try:
        repair_raw = await ports.llm().complete(
            _STRENGTHEN_AGENT,
            system=finetune_prompt,
            user=repair_user,
            temperature=0.55,
        )
        repaired = _normalize_block_output(_strip_codefence(repair_raw), kind=kind)
        if repaired and is_substantive_enhancement(original, repaired):
            _log_style_issues(lint_strengthen_text(repaired, keep_terms), kind=kind, mode=mode)
            return repaired, f"{pipeline}+repair"
    except Exception as exc:  # noqa: BLE001
        logger.warning("strengthen: cosmetic repair упал, отдаём черновик: %s", exc)
    return out, pipeline


async def strengthen_section(
    kind: str,
    text: str,
    *,
    account_id: int,
    role_title: str = "",
    keep_terms: list[str] | None = None,
    mode: str = "refine",
    ctx: StrengthenContext | None = None,
) -> StrengthenResult:
    """Critique-loop: reserve-тир draft → reserve-тир critique → reserve-тир finetune.

    `mode`:
    - `refine` (по умолчанию): исходный текст блока подаётся в LLM, та переписывает его.
    - `rewrite`: исходный текст НЕ подаём (LLM не ленится на переформулировке). Вместо него
      в draft идёт фактический био-материал резюме (должность/навыки/опыт) + контекст рынка.
      Finetune тоже без исходника. Под «Обо мне» — пишет с нуля по материалу резюме.

    `ctx` — готовый StrengthenContext (FR2-32 ats-fit гоняет несколько блоков параллельно и
    собирает контекст один раз). Если None — собираем сами, как раньше.

    Нет ключа OpenRouter → `LlmError`. Слишком короткий текст в refine → `ValueError`
    (в rewrite текст может быть пустым — он не используется). GLM недоступен/упал → fallback
    на single-model rewrite (draft как final).
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    if mode not in ("refine", "rewrite"):
        raise ValueError(f"неизвестный mode: {mode}")
    if mode == "refine" and (not text or len(text.strip()) < 30):
        raise ValueError("текст блока слишком короткий для усиления")

    if ctx is None:
        ctx = await build_strengthen_context(account_id=account_id)
    if mode == "rewrite" and not ctx.bio_material:
        # Без био-материала rewrite бессмысленен — LLM не из чего строить текст.
        raise ValueError("нет структурированного резюме для rewrite-режима")

    from core.domains.profile.structured_store import read_resume_data_for_account

    data = await read_resume_data_for_account(account_id)

    text_clean = text.strip()
    terms = keep_terms or []

    # Промпты: в rewrite — свой системник (без исходника), в refine — классический.
    from core.domains.profile.llm import (
        STRENGTHEN_CRITIC,
        STRENGTHEN_DRAFT,
        STRENGTHEN_FINETUNE,
        STRENGTHEN_REWRITE,
    )

    if mode == "rewrite":
        draft_prompt = _load_prompt(STRENGTHEN_REWRITE, data=data)
    else:
        draft_prompt = _load_prompt(STRENGTHEN_DRAFT, data=data)
    finetune_prompt = _load_prompt(STRENGTHEN_FINETUNE, data=data)
    critic_prompt_path = STRENGTHEN_CRITIC

    # --- Шаг 1: Draft (тир resume_strengthen → reserve) ---
    if mode == "rewrite":
        draft_user = _build_rewrite_user_prompt(kind, role_title, terms, ctx)
        original_for_steps = ""  # исходник в rewrite не используем
    else:
        draft_user = _build_user_prompt(kind, text_clean, role_title, terms, ctx)
        original_for_steps = text_clean
    draft_raw = await ports.llm().complete(
        _STRENGTHEN_AGENT,
        system=draft_prompt,
        user=draft_user,
        temperature=0.5,
    )
    draft = _normalize_block_output(_strip_codefence(draft_raw), kind=kind)
    if not draft:
        raise LlmError("LLM вернул пустой черновик (шаг 1)")

    # --- Шаг 2: Critique (тир resume_strengthen_critic → reserve); падение → single ---
    critique: CritiqueResult | None = None
    if critic_prompt_path:
        try:
            critic_system = _load_prompt(critic_prompt_path, data=data)
            critic_user = _build_critic_prompt(
                kind, role_title, terms, original_for_steps, draft, ctx
            )
            critique = await ports.llm().structured(
                _CRITIC_AGENT,
                system=critic_system,
                user=critic_user,
                schema=CritiqueResult,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 — критика опциональна, не валим пайплайн
            logger.warning("strengthen: critique-шаг пропущен (%s): %s", _CRITIC_AGENT, exc)
            critique = None

    # --- Шаг 3: Finetune (тир resume_strengthen) — только если критика есть ---
    if critique is None:
        event(
            logger,
            "LLM",
            "strengthen %s/%s: single (critique пропущен), %d симв.",
            kind,
            mode,
            len(draft),
            kind=kind,
            mode=mode,
            pipeline="single",
            chars=len(draft),
            level=logging.WARNING,
        )
        final_text, pipe = await _apply_output_guards(
            draft,
            kind=kind,
            mode=mode,
            original=original_for_steps,
            keep_terms=terms,
            data=data,
            finetune_prompt=finetune_prompt,
            role_title=role_title,
            pipeline="single",
        )
        return StrengthenResult(
            text=final_text,
            draft=draft,
            critique=None,
            pipeline=pipe,
        )

    finetune_user = _build_finetune_prompt(
        kind, role_title, original_for_steps, draft, critique, ctx
    )
    final_raw = await ports.llm().complete(
        _STRENGTHEN_AGENT,
        system=finetune_prompt,
        user=finetune_user,
        temperature=0.4,
    )
    final = _strip_codefence(final_raw)
    if not final:
        # Финал пуст — отдаём draft, не теряем результат совсем.
        logger.warning("strengthen: finetune-шаг вернул пусто, отдаём draft как final")
        final = draft

    final_text, pipe = await _apply_output_guards(
        final,
        kind=kind,
        mode=mode,
        original=original_for_steps,
        keep_terms=terms,
        data=data,
        finetune_prompt=finetune_prompt,
        role_title=role_title,
        pipeline="critique_loop",
    )

    event(
        logger,
        "LLM",
        "strengthen %s/%s: critique_loop, вердикт=%s, %d симв.",
        kind,
        mode,
        critique.verdict,
        len(final_text),
        kind=kind,
        mode=mode,
        pipeline=pipe,
        verdict=critique.verdict,
        chars=len(final_text),
    )
    return StrengthenResult(
        text=final_text,
        draft=draft,
        critique=critique,
        pipeline=pipe,
    )


__all__ = ["CritiqueIssue", "CritiqueResult", "StrengthenResult", "strengthen_section"]
