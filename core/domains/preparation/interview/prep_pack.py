"""RD-16: авто-бриф подготовки под конкретный этап конкретной вакансии.

Кнопка «Собрать подготовку» на TechPage (вакансия+формат уже выбраны) сводит в один бриф то, что
сейчас приходится собирать вручную из 4 мест:
- что спросят: профиль компании (`core.domains.preparation.interview.company_profiles`) + текст вакансии;
- слабые темы: разборы ЭТОГО формата по ВСЕМ прошлым собесам (`core.domains.preparation.debrief`,
  `analysis.topics_to_study` — провал на лайвкодинге у одной компании учит перед лайвкодингом
  у другой);
- фидбек рекрутёров ПО ЭТОЙ вакансии (`core.domains.pipeline.stage_outcome`);
- легенда под вакансию (кэш пакета скрининга, `core.domains.preparation.screening.context.
  load_self_pres_context`) — не как отдельная секция брифа, а как ограничение стиля: бриф не
  должен предлагать подачу, которая противоречит тому, что кандидат уже рассказывает о себе.

Персист — `core.domains.preparation.prep_pack` (один бриф на vacancy+stage, перегенерация затирает старый текст,
фронт ревьюит diff перед сохранением — тот же паттерн, что «Перегенерировать легенду»).
"""

from __future__ import annotations

import logging

from core.config import get_settings
from core.domains.opportunities.prompt import load_candidate_identity
from core.domains.preparation.interview.company_profiles import CompanyProfile
from core.domains.preparation.interview.prep_context import gather_prep_context
from core.domains.preparation.models import STAGE_LABELS, VacancyRecord
from core.domains.preparation.screening.context import load_self_pres_context
from core.domains.preparation.vacancy_context import truncate_vacancy_text
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

# Те же формулировки формата этапа, что генерация вопросов (`core.interview.prep._STAGE_HINTS`) —
# не импортируем оттуда (модуль приватный), держим короткую копию под нужды брифа.
_STAGE_HINTS: dict[str, str] = {
    "screening": "HR-скрининг: мотивация, гибкие требования, проверка реальности опыта.",
    "tech": "Техничка: глубокие вопросы по стеку вакансии + прикладной кейс.",
    "theory": (
        "Теория: глубокие концептуальные вопросы по фундаменту стека вакансии - ключевые темы "
        "своего направления из резюме."
    ),
    "system_design": "System design: один большой кейс на проектирование системы под стек вакансии.",
    "live_coding": "Live coding: алгоритмы плюс практическая задача под стек вживую.",
    "business_case": (
        "Бизнес-кейс: продуктовая задача, нужно предложить решение под свою специализацию с impact."
    ),
    "final": "Финал с тимлидом/head of: команда, roadmap, ownership.",
    "hr_final": "HR-финал: деньги, формат, условия. Технических вопросов нет.",
    "other": "Формат заранее не известен - готовь смешанный набор ожиданий.",
}


def _build_company_block(stage: str, profile: CompanyProfile | None) -> str:
    if profile is None:
        return ""
    note = profile.stage_notes.get(stage, "")
    note_line = f"\nФормат этапа в «{profile.name}»: {note}" if note else ""
    return f"\nПрофиль компании «{profile.name}»: {profile.summary}{note_line}\n"


async def _build_system_prompt(
    stage: str,
    profile: CompanyProfile | None,
    weak_topics_block: str,
    recruiter_feedback_block: str,
    legend_content: str,
    strong_answers_block: str,
    asked_questions_block: str,
    *,
    account_id: int | None,
) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    stage_label = STAGE_LABELS.get(stage, stage)
    stage_hint = _STAGE_HINTS.get(stage, "")
    company_block = _build_company_block(stage, profile)
    legend_block = legend_content.strip() or "(легенда ещё не собрана)"
    resume_data = await read_resume_data_for_account(account_id)
    identity = load_candidate_identity(data=resume_data)

    return f"""Ты - карьерный коуч. Собираешь короткий бриф подготовки к конкретному этапу собеса
для кандидата ({identity}) - цель и вилка см. «Желаемая должность и зарплата» в резюме. Кандидат
читает бриф за 2-3 часа до собеса на одном экране - без воды, без общих советов «расскажите о
себе».

## Этап

{stage_label}. {stage_hint}
{company_block}
## Легенда кандидата (что он рассказывает о себе на скрининге)

{legend_block}

Держи бриф в согласии с легендой - не предлагай подачу, которая ей противоречит.

## Слабые темы из прошлых разборов собесов этого формата (по всем компаниям)

{weak_topics_block}

## Фидбек рекрутёров по этой вакансии

{recruiter_feedback_block}

## Сильные ответы кандидата на прошлых собесах (козыри)

{strong_answers_block or "(пока нет)"}

## Уже заданные вопросы на прошлых этапах ЭТОЙ вакансии (с пометкой слабо/сильно)

{asked_questions_block or "(прошлых этапов по этой вакансии не было)"}

## Что делаешь

Собери бриф ровно из пяти секций, в этом порядке - сначала «как себя вести», потом «что учить»:

### Акценты этапа
3-5 пунктов, что подчеркнуть на этом собесе: козыри из блока сильных ответов (если он не пуст),
сигналы фидбека рекрутёра, топ-приоритеты вакансии. Козырей/фидбека нет - пиши только по
приоритетам вакансии, не выдумывай факты, которых не передано.

### Не повторить
2-3 пункта, ТОЛЬКО если среди уже заданных вопросов есть отмеченные как слабые: конкретная ошибка
+ как поступить иначе. Формулировку "как иначе" бери дословно из пометки в блоке "уже заданные
вопросы" (совет там уже готов дебрифом) - не сочиняй заново. Отметок нет - не пиши раздел вовсе.

### Что спросят
3-5 пунктов: конкретика по формату этапа у этой компании (если профиль известен) и по стеку
вакансии. Никаких общих слов - что реально прозвучит именно тут.

### Твои слабые темы
Если список слабых тем не пуст - 2-4 пункта: что подтянуть и как коротко закрыть пробел на этом
собесе. Если список пуст - одна строка: «Провалов этого формата в истории нет, отдельного фокуса
не требуется».

### Фидбек рекрутёра
Только если фидбек по вакансии есть - выжимка, что рекрутёр отметил и что важно показать на этом
этапе. Если фидбека нет - не пиши этот раздел вообще (не выдумывай).

## Правила

1. Markdown: заголовки `###`, списки, **жирный** для ключевых терминов.
2. Рубленые строки, без канцелярита, без маркеров автогенерации («как ИИ-ассистент», «важно
   отметить», «в заключение»).
3. Никаких длинных тире - только обычный минус.
4. Опирайся ТОЛЬКО на переданные факты. Не выдумывай фидбек или профиль компании, которого нет.
5. Без кода, код-блоков и формул (`$...$`) - бриф читают за 2-3 часа до собеса на одном экране,
   а не показывают на нём код. Пункты - короткие тезисы, не абзацы.
6. Не используй `---`, таблицы, блоки цитат `>`, ссылки `[text](url)` - фронт (`MarkdownView`) их
   не рендерит.
"""


def _build_user_prompt(record: VacancyRecord, stage: str) -> str:
    title = record.title or "?"
    company = record.company or "?"
    salary = record.salary_text or "не указано"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=6000)
    score = record.score
    overall = score.overall_score if score else "?"

    return f"""## Вакансия

Компания: {company}
Позиция: {title}
Зарплата (вакансия): {salary}
Скор: {overall}/100

### Текст вакансии

{text}

Собери бриф подготовки под этап «{STAGE_LABELS.get(stage, stage)}» (см. инструкции). Верни ТОЛЬКО
markdown брифа, без текста до/после.
"""


async def generate_prep_pack(
    record: VacancyRecord, stage: str, profile: CompanyProfile | None = None, *, account_id: int
) -> str:
    """Собрать бриф подготовки под этап. Ничего не сохраняет — кандидат для ревью на фронте.

    Нет ключа OpenRouter → `LlmError`; бюджетные стоп-краны пробрасываются (роутер → 429).
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    # RD-21: сбор слабых тем + фидбека рекрутёра централизован в prep_context — отдельного сбора
    # здесь больше не нужно, бриф стал витриной того же контекста, что видит генерация вопросов.
    context = await gather_prep_context(record.vacancy_id or "", stage, account_id=account_id)

    try:
        legend_content = await load_self_pres_context(
            record.vacancy_id or "", account_id=account_id, include_hr_questions=False
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → бриф без легенды
        logger.debug("prep_pack: легенда недоступна: %s", exc)
        legend_content = ""

    system = await _build_system_prompt(
        stage,
        profile,
        context.weak_topics or "(истории разборов этого формата пока нет)",
        context.recruiter_feedback or "(фидбека рекрутёра по этой вакансии пока нет)",
        legend_content,
        context.strong_answers,
        context.asked_questions,
        account_id=account_id,
    )
    user = _build_user_prompt(record, stage)
    content = (
        await ports.llm().complete("prep_pack", system=system, user=user, temperature=0.4)
    ).strip()
    event(
        logger,
        "LLM",
        "бриф подготовки собран: %d симв. (легенда=%s)",
        len(content),
        "есть" if legend_content else "нет",
        vacancy_id=record.vacancy_id,
        stage=stage,
        chars=len(content),
        legend_missing=not legend_content,
    )
    return content


__all__ = ["generate_prep_pack"]
