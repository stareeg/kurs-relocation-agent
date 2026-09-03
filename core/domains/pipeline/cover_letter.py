"""Короткое сопроводительное письмо по вакансии.

Без фанатизма: письмо нужно дай бог на 10% вакансий, 95% HR его не читают. Поэтому движок один
маленький — резюме + текст вакансии → 1-2 абзаца в стиле владельца (рубленые строки, без длинных
тире и двоеточий, ПРОМ капсом, активные глаголы; CLAUDE.md). Plain text под поле отклика hh, без
markdown. Тир — основная модель через имя агента `cover_letter` (LlmFeature / `agent`).

Скоринг/инструкции (вилка ЗП, приоритеты) сюда НЕ подмешиваем: письмо про соответствие, не про
деньги (анкор ЗП — это переговоры, не первый контакт). Берём факты резюме + вакансию; FR3-54 —
при наличии кэша пакета скрининга подмешиваем oral_pitch/мосты к вакансии/why (без нового LLM).

Правка 2026-08-20 (жалоба «письмо как у всех»): промпт раньше просил один яркий факт/метрику из
резюме и вплести его в контекст вакансии — на практике модель регулярно брала метрику саму по себе,
и получался мини-пересказ резюме («поднял X на Y%»), не объясняющий, почему этот факт вообще
релевантен именно этой вакансии. Алгоритм ниже требует явного моста «опыт → боль вакансии»: не
просто факт, а обоснование, при каком совпадении контекста (домен/масштаб/тип задачи, не
обязательно дословный стек) кандидат подходит на роль.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from core.config import get_settings
from core.domains.opportunities.prompt import load_candidate_identity, load_resume
from core.domains.preparation.models import VacancyRecord
from core.domains.preparation.vacancy_context import truncate_vacancy_text
from core.domains.profile.international import (
    InternationalReadiness,
    derive_international_readiness,
)
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.text import style_lint
from core.kernel.text.style_lint import StyleIssue
from core.platform.observability import event

logger = logging.getLogger(__name__)

LetterLang = Literal["ru", "en"]

# Ник из резюме / t.me / @user → канон «@nickname» для первой строки письма.
_TG_HANDLE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me/|telegram\.me/)?@?([A-Za-z][A-Za-z0-9_]{4,31})\s*$",
    re.I,
)

_SYSTEM_PROMPT = """Ты пишешь короткое сопроводительное письмо за конкретного кандидата ({identity}) под конкретную вакансию.

## Резюме кандидата

{resume}
{prep_block}
## Контекст: как это письмо реально читают в 2026

Сопроводительное почти всегда читает HR, не технический специалист - она видит список ключевых
слов из вакансии и очень поверхностное описание сути роли. Многие HR резюме уже не читают сами,
а скармливают его нейросети - и по той же логике шаблонные "ИИ-письма" 2024 года распознают с
одного взгляда. Задача письма - не пересказ резюме короче, а конкретный ответ на вопрос "почему
именно этого кандидата стоит рассмотреть на эту роль" - через явное пересечение опыта, а не
перечисление того, чем кандидат занимался на прошлом месте.

## Алгоритм

1. Найди в тексте вакансии 1-2 КОНКРЕТНЫХ требования или боли по сути роли (не должность целиком,
   а конкретный процесс/проблему/контекст - домен, масштаб, устройство команды, тип задач).
2. Для каждого найди в резюме кандидата РЕАЛЬНОЕ пересечение опыта - не первую попавшуюся яркую
   метрику, а именно то место, где кандидат решал задачу того же рода, в похожем контексте или на
   похожей развилке. Пересечение может быть по домену, по масштабу, по типу проблемы - не
   обязательно дословное совпадение стека или должности.
3. Письмо строится вокруг ответа "почему меня стоит рассмотреть на эту роль", а не вокруг
   пересказа задач с прошлого места. Каждый факт резюме, который попадает в письмо, должен явно
   объяснять, чем он релевантен именно этой вакансии - не голое "я делал X", а связка "я делал X
   в похожей ситуации, поэтому здесь пригожусь" (без этих слов буквально, но с этой логикой).
4. Первая строка - хук: конкретное пересечение опыта и боли вакансии, а не "меня заинтересовала
   ваша вакансия" и не голая метрика без объяснения, зачем она тут.
5. Дальше - 1-2 предложения, которые ЗАКРЫВАЮТ аргумент из хука: почему это пересечение опыта
   реально решает задачу вакансии. Не добавляй второй несвязанный факт резюме просто для веса -
   один точный мост убедительнее списка достижений.

Если есть блок «Подготовка под вакансию» - опирайся на его акценты и формулировки, не копируй
устный рассказ целиком.

## Тон

Уверенно, сухо, ёмко - как если бы кандидат сам написал HR короткое сообщение в мессенджере, а не
составлял официальный документ. Пиши на языке результата и практических следствий (что
изменилось, ускорилось, подешевело, перестало ломаться) - это одинаково понятно и HR по ключевым
словам, и нанимающему менеджеру по сути.

## Категорически запрещено (маркеры ИИ-письма, HR узнаёт их с одного взгляда)

- Голый пересказ задач/достижений с прошлого места без явной привязки к тому, что нужно именно в
  этой вакансии - это то же самое резюме, просто короче, и выглядит как письмо "под копирку".
- Вводные слова-паразиты в начале предложения: "В заключение", "Важно отметить".
- Пафосные прилагательные: "революционный", "инновационный", "передовой", "уникальный",
  "беспрецедентный", "динамичный" (в значении "энергичный", не техническом термине).
- Корпоративная вода: "стремлюсь внести вклад", "рад возможности стать частью", "высокая
  мотивация", "глубокая экспертиза".
- Банальные комплименты компании: "вы лидеры рынка", "меня вдохновляют ваши продукты".

## Жёсткие правила формата

1. Объём - 1-2 коротких абзаца, не длиннее. Всего 5-9 строк. Это сопроводительное, не резюме.
2. Каждое смысловое предложение на своей строке, короткие активные глаголы (тащил, собрал,
   поднял, снизил, ускорил), без канцелярита (никаких "осуществлял", "реализовывал",
   "позволяет", "способствует").
3. Пунктуация - НИКАКИХ длинных тире, только обычный минус. Никаких двоеточий перед перечислением.
4. ПРОМ капсом, если упоминаешь продакшен. Англицизмы - только точные названия технологий и
   термины из резюме кандидата, capitalization сохраняй.
5. Без воды и обрамления - не начинай с "Здравствуйте, меня зовут", не заканчивай "буду рад
   обсудить". Сразу по сути, резко заверши в одну строку. Telegram-ник (@…) НЕ пиши сам —
   его добавят отдельно первой строкой.
6. Не упоминай зарплату, деньги, релокацию - письмо только про соответствие задачам.
7. Не выдумывай факты, которых нет в резюме. Только plain text, без markdown (#, *, -), без эмодзи.
8. Верни ТОЛЬКО текст письма. Никаких пояснений до или после.
"""

# Э4.4 dual_employment_and_contracting_2026.md: письмо под международный рынок (US/EU/EMEA
# распределённая команда/контракт) - отдельный промпт, не ветка RU-версии выше (два разных
# набора правил в одном промпте деградируют в кашу). Резюме/identity сюда подставляются УЖЕ
# анонимизированными вызывающей стороной (см. `_generate_en`), если включена политика раскрытия -
# промпт про это не знает, он просто получает готовый markdown.
_SYSTEM_PROMPT_EN = """You are writing a short cover letter for a specific candidate ({identity}) applying to a specific job.

## Candidate resume

{resume}

## Context: who actually reads this

You are writing to a hiring manager or founder building a distributed/remote team - often not a
native English speaker. They value autonomy, delivery without close supervision, working across
time zones, and clear written communication. They do not want a résumé restated in prose.

## Algorithm

1. Find ONE concrete pain or requirement in the job text (a specific process/problem/context -
   domain, scale, team setup, kind of task - not the job title as a whole).
2. Find the ONE place in the candidate's experience that shows a real match to that pain - not
   the flashiest metric, the place where the candidate solved a problem of the same kind, in a
   comparable context. Match by domain/scale/problem type, not necessarily by exact tech stack.
3. Build the letter around that single bridge "pain -> matching experience -> why it transfers."
   Do not add a second unrelated fact just for weight - one precise bridge beats a list of
   achievements.
4. First line is the hook: the concrete overlap between experience and the job's pain - not
   "I am excited to apply" and not a bare metric with no explanation of why it matters here.
5. Add one line about availability - overlap hours and contract form (from the facts given below) -
   this is what actually filters contractors, and silence on it reads as risk.
{availability_line}
## Forbidden (AI-letter markers, any hiring manager spots them instantly)

- "I am excited to apply", "I am writing to express my interest", "proven track record",
  "passionate about", "fast-paced environment", "team player", "hit the ground running",
  "wear many hats", "results-driven", "I believe I would be a great fit", "leverage my
  expertise", "value-add", "synergy", "best-in-class".
- Restating past responsibilities without tying them to this specific job's pain.
- Praising the company ("you are industry leaders", "I admire your product").
- Mentioning salary, relocation, or visa status.

## Hard format rules

1. 5-9 short lines total, plain text. This is a cover letter, not a résumé.
2. One idea per line, short active verbs (built, cut, shipped, led), no corporate filler
   ("leverage", "facilitate", "utilize").
3. No em dashes or en dashes, no colons before a list. Plain comma or a new sentence.
4. No "Dear Hiring Manager" opener if there is no addressee name, no "Best regards" closer -
   end on the last concrete line. A Telegram/contact handle, if any, is prepended separately -
   do not write it yourself.
5. Do not invent facts absent from the resume. No markdown (#, *, -), no emoji.
6. Return ONLY the letter text. No explanation before or after.
"""

# Ремонт письма после линта - переиспользуем общий анти-slop линтер (core.kernel.text.style_lint),
# тот же, что HR-черновики/легенда/усиление резюме. Англицизмы не проверяем: короткое письмо
# держится на 1-2 точных технологиях из резюме, порог легко ложно срабатывает на них.
_LINT_CHECKS: tuple[str, ...] = ("officialese", "punctuation", "monotony", "cliches", "line_length")
_LINT_CHECKS_EN: tuple[str, ...] = style_lint.EN_CHECKS


def _build_repair_user_prompt(letter: str, issues: list[StyleIssue]) -> str:
    return f"""Черновик письма:

{letter}

## Нарушения стиля - исправить каждое

{style_lint.issues_to_prompt(issues)}

Перепиши письмо целиком, устранив каждый пункт. Факты и объём (1-2 абзаца) не меняй.
Верни ТОЛЬКО текст письма."""


def _build_repair_user_prompt_en(letter: str, issues: list[StyleIssue]) -> str:
    return f"""Draft letter:

{letter}

## Style violations - fix every one

{style_lint.issues_to_prompt(issues)}

Rewrite the whole letter, fixing every point above. Keep the facts and the length (5-9 lines).
Return ONLY the letter text."""


def _availability_line(intl: InternationalReadiness) -> str:
    """Строка про пересечение часов/форму контракта для EN-промпта (§Э4.4 «условия»)."""
    bits: list[str] = []
    overlap = {region: hours for region, hours in (intl.overlap or {}).items() if hours > 0}
    if overlap:
        top = sorted(overlap.items(), key=lambda kv: -kv[1])[:2]
        bits.append(", ".join(f"{h}h overlap with {region}" for region, h in top))
    forms = [f for f in (intl.contract_forms or []) if f]
    if forms:
        bits.append("open to: " + ", ".join(forms))
    if not bits:
        return ""
    return (
        "\nFacts to weave into that availability line (do not just list them verbatim): "
        + "; ".join(bits)
        + ".\n"
    )


def _build_user_prompt(record: VacancyRecord) -> str:
    company = record.company or "не указана"
    title = record.title or "не указана"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=6000)
    return f"""## Вакансия

Компания: {company}
Позиция: {title}

### Текст вакансии

{text}

Напиши короткое сопроводительное под эту вакансию. Верни только текст письма.
"""


def _build_user_prompt_en(record: VacancyRecord) -> str:
    company = record.company or "not specified"
    title = record.title or "not specified"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=6000)
    return f"""## Job posting

Company: {company}
Position: {title}

### Job text

{text}

Write a short cover letter for this job. Return only the letter text.
"""


async def _prep_block_for_letter(record: VacancyRecord, *, account_id: int) -> str:
    """FR3-54: срез кэша пакета (без hr_questions). Нет кэша → пусто."""
    vacancy_id = (record.vacancy_id or "").strip()
    if not vacancy_id:
        return ""
    try:
        from core.domains.preparation.screening.context import format_self_pres_for_cover_letter
        from core.domains.preparation.screening_questions import get_screening_questions

        saved = await get_screening_questions(vacancy_id, account_id=account_id)
        body = format_self_pres_for_cover_letter(saved)
    except Exception as exc:  # noqa: BLE001 — письмо без пакета, не падаем
        logger.debug("cover_letter: пакет скрининга недоступен: %s", exc)
        return ""
    if not body:
        return ""
    return f"\n## Подготовка под вакансию (кэш, уже собрано)\n\n{body}\n"


async def telegram_handle_from_resume(*, account_id: int) -> str:
    """Ник Telegram из резюме ЭТОГО аккаунта (`resume_data.contacts.telegram`) → `@nickname`;
    пусто если нет/мусор.

    Аккаунт-скоуп обязателен: на общем мультиаккаунтном хостинге (CLAUDE.md) чужой ник в
    письме — не косметика, а реальная путаница для HR (не тот контакт получит ответ).
    Раньше звал `read_default_resume_data()` (легаси, единственный дефолтный аккаунт) —
    заменено на канонический `read_resume_data_for_account(account_id)`.
    """
    try:
        from core.domains.profile.structured_store import read_resume_data_for_account

        resume = await read_resume_data_for_account(account_id)
        raw = (resume.contacts.telegram or "").strip()
    except Exception as exc:  # noqa: BLE001 — письмо без ника, не падаем
        logger.debug("cover_letter: telegram из резюме недоступен: %s", exc)
        return ""
    return normalize_telegram_handle(raw)


def normalize_telegram_handle(raw: str) -> str:
    """`@user` / `user` / `t.me/user` → `@user`; иначе пусто."""
    s = (raw or "").strip()
    if not s:
        return ""
    m = _TG_HANDLE_RE.fullmatch(s) or _TG_HANDLE_RE.search(s)
    if not m:
        return ""
    return f"@{m.group(1)}"


def prepend_telegram_handle(letter: str, handle: str) -> str:
    """Первая строка — `@nickname`, без дубля если модель уже начала с него."""
    body = (letter or "").strip()
    nick = (handle or "").strip()
    if not nick or not body:
        return body
    first = body.splitlines()[0].strip()
    if first.lower() == nick.lower() or first.lower().startswith(f"{nick.lower()} "):
        return body
    return f"{nick}\n{body}"


async def _call_letter(
    system: str, user: str, *, feature: str = "cover_letter", temperature: float = 0.6
) -> str:
    raw = await ports.llm().complete(feature, system=system, user=user, temperature=temperature)
    letter = raw.strip()
    # Срезаем случайную markdown-обёртку, если модель всё же её добавила.
    if letter.startswith("```"):
        letter = letter.strip("`").strip()
    if not letter:
        raise LlmError("LLM вернул пустое письмо")
    return letter


async def _resolve_effective_lang(lang: LetterLang | None, *, account_id: int) -> LetterLang:
    if lang is not None:
        return lang
    from core.domains.profile.international import detect_resume_language
    from core.domains.profile.structured_store import read_resume_data_for_account

    try:
        resume = await read_resume_data_for_account(account_id)
    except Exception as exc:  # noqa: BLE001 — нет резюме → безопасный дефолт продукта
        logger.debug("cover_letter: резюме недоступно для автодетекта языка: %s", exc)
        return "ru"
    return detect_resume_language(resume)


async def _generate_ru(record: VacancyRecord, *, account_id: int) -> str:
    """RU-путь — поведение не менялось с версии до Э4.4 (hh-стиль, скрининг-мост).

    S-critical (2026-08-26): раньше звал `load_resume()`/`load_candidate_identity()` без `data=` —
    это легаси файловый/дефолт-аккаунтный кэш (`core.domains.opportunities.prompt._render_resume`),
    отдающий резюме ВЛАДЕЛЬЦА инсталляции для ЛЮБОГО account_id. На общем мультиаккаунтном хостинге
    письмо друга собиралось из чужого (владельца) опыта. Резюме резолвится явно, как уже делает
    `_generate_en`/`_resolve_en_resume` ниже.
    """
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    prep_block = await _prep_block_for_letter(record, account_id=account_id)
    system = _SYSTEM_PROMPT.format(
        resume=load_resume(data=resume_data),
        identity=load_candidate_identity(data=resume_data),
        prep_block=prep_block,
    )
    letter = await _call_letter(system, _build_user_prompt(record))

    issues = style_lint.lint(letter, checks=_LINT_CHECKS)
    if not issues:
        event(
            logger,
            "LLM",
            "сопроводительное собрано: %d симв., 0 нарушений стиля",
            len(letter),
            vacancy_id=record.vacancy_id,
            chars=len(letter),
            repaired=False,
            lang="ru",
        )
        return letter

    logger.info("сопроводительное: %d нарушений стиля, запускаю ремонт", len(issues))
    try:
        letter = await _call_letter(system, _build_repair_user_prompt(letter, issues))
    except LlmError as exc:
        event(
            logger,
            "LLM",
            "сопроводительное: ремонт не удался, отдаю черновик как есть: %s",
            exc,
            vacancy_id=record.vacancy_id,
            issues_before=len(issues),
            repaired=False,
            lang="ru",
            level=logging.WARNING,
        )
        return letter

    issues_after = style_lint.lint(letter, checks=_LINT_CHECKS)
    event(
        logger,
        "LLM",
        "сопроводительное: после ремонта нарушений %d (было %d)",
        len(issues_after),
        len(issues),
        vacancy_id=record.vacancy_id,
        issues_before=len(issues),
        issues_after=len(issues_after),
        repaired=True,
        lang="ru",
    )
    return letter


async def _resolve_en_resume(*, account_id: int) -> tuple[str, str, InternationalReadiness]:
    """Резюме под EN-письмо: (markdown, identity, intl) — анонимизировано, если политика включена.

    `to_markdown`/`candidate_identity_line` считаются от УЖЕ анонимизированной ResumeData,
    не от файлового кэша `load_resume()`/`load_candidate_identity()` — те читают резюме в обход
    анонимизации и протащили бы настоящее имя компании через identity-строку.
    """
    from core.domains.profile.anonymize import (
        anonymize_resume,
        current_employer_experience,
        get_disclosure_policy,
    )
    from core.domains.profile.employer_descriptor import get_or_create_employer_descriptor
    from core.domains.profile.identity import candidate_identity_line
    from core.domains.profile.model import to_markdown
    from core.domains.profile.structured_store import read_resume_data_for_account

    data = await read_resume_data_for_account(account_id)
    policy = await get_disclosure_policy(account_id=account_id)
    effective_data = data

    hide_current = policy.hide_current_employer or policy.hide_all_employers
    current_exp = current_employer_experience(data) if hide_current else None
    if hide_current and current_exp is not None and current_exp.company.strip():
        try:
            descriptor = await get_or_create_employer_descriptor(
                account_id,
                company=current_exp.company,
                industry=current_exp.industry,
                area=current_exp.area,
                role_context=current_exp.position,
            )
        except Exception as exc:  # noqa: BLE001 — письмо без анонимизации лучше, чем падение
            logger.warning("cover_letter_intl: дескриптор работодателя не построен: %s", exc)
            descriptor = None
        if descriptor is not None:
            from core.domains.opportunities.companies.normalize import (
                normalize_company_deterministic,
            )

            canonical = normalize_company_deterministic(current_exp.company)
            effective_data = anonymize_resume(
                data, policy=policy, descriptors={canonical: descriptor}, lang="en"
            )
    elif policy.hide_public_links or policy.coarse_dates or policy.coarse_city:
        effective_data = anonymize_resume(data, policy=policy, lang="en")

    intl = derive_international_readiness(
        data
    )  # факты кандидата, не про работодателя - не анонимизируем
    return to_markdown(effective_data), candidate_identity_line(effective_data), intl


async def _generate_en(record: VacancyRecord, *, account_id: int) -> str:
    """EN-путь под международный рынок (Э4.4) — отдельный промпт/фича, анти-slop на EN_CHECKS."""
    resume_md, identity, intl = await _resolve_en_resume(account_id=account_id)

    system = _SYSTEM_PROMPT_EN.format(
        resume=resume_md,
        identity=identity,
        availability_line=_availability_line(intl),
    )
    letter = await _call_letter(
        system, _build_user_prompt_en(record), feature="cover_letter_intl", temperature=0.4
    )

    issues = style_lint.lint(letter, checks=_LINT_CHECKS_EN)
    if not issues:
        event(
            logger,
            "LLM",
            "сопроводительное (EN) собрано: %d симв., 0 нарушений стиля",
            len(letter),
            vacancy_id=record.vacancy_id,
            chars=len(letter),
            repaired=False,
            lang="en",
        )
        return letter

    logger.info("сопроводительное (EN): %d нарушений стиля, запускаю ремонт", len(issues))
    try:
        letter = await _call_letter(
            system,
            _build_repair_user_prompt_en(letter, issues),
            feature="cover_letter_intl",
            temperature=0.4,
        )
    except LlmError as exc:
        event(
            logger,
            "LLM",
            "сопроводительное (EN): ремонт не удался, отдаю черновик как есть: %s",
            exc,
            vacancy_id=record.vacancy_id,
            issues_before=len(issues),
            repaired=False,
            lang="en",
            level=logging.WARNING,
        )
        return letter

    issues_after = style_lint.lint(letter, checks=_LINT_CHECKS_EN)
    event(
        logger,
        "LLM",
        "сопроводительное (EN): после ремонта нарушений %d (было %d)",
        len(issues_after),
        len(issues),
        vacancy_id=record.vacancy_id,
        issues_before=len(issues),
        issues_after=len(issues_after),
        repaired=True,
        lang="en",
    )
    return letter


async def generate_cover_letter(
    record: VacancyRecord, *, account_id: int, lang: LetterLang | None = None
) -> tuple[str, LetterLang]:
    """Резюме + вакансия → короткое сопроводительное (plain text, 1-2 абзаца) + язык.

    `lang=None` — язык выводится из текста резюме (`detect_resume_language`, Э4.4): кириллица
    в прозе резюме → русское письмо, латиница → английское. Явный `lang` (переключалка в
    дровере/расширении) побеждает вывод. Нет ключа OpenRouter → `LlmError` (как prep, не молча
    пустой текст). Бюджетные стоп-краны пробрасываются вызывающему (роутер маппит в 429).
    Анти-slop: один ремонтный вызов при нарушениях линтера — максимум 2 LLM-вызова на сценарий.
    Telegram-ник из резюме (`@nickname`) добавляется первой строкой на обоих языках.
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    effective_lang = await _resolve_effective_lang(lang, account_id=account_id)
    if effective_lang == "en":
        letter = await _generate_en(record, account_id=account_id)
    else:
        letter = await _generate_ru(record, account_id=account_id)

    telegram_handle = await telegram_handle_from_resume(account_id=account_id)
    return prepend_telegram_handle(letter, telegram_handle), effective_lang


__all__ = [
    "LetterLang",
    "generate_cover_letter",
    "normalize_telegram_handle",
    "prepend_telegram_handle",
    "telegram_handle_from_resume",
]
