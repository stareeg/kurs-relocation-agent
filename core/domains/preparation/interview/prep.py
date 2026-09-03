"""Генерация вопросов под собес и feedback по ответам.

Транспорт — порт `kernel.ports.llm()` (фича `prep`).
L-12: `generate_prep_questions` — structured (`_PrepQuestionsOut`), не complete+ручной JSON.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.app.pipeline import Pipeline, PipelineError, Step
from core.config import get_settings
from core.domains.opportunities.prompt import (
    CANDIDATE_IDENTITY_TOKEN,
    load_candidate_identity,
    load_instructions,
    load_resume,
)
from core.domains.preparation.interview.company_profiles import CompanyProfile
from core.domains.preparation.interview.prep_context import gather_prep_context
from core.domains.preparation.models import (
    CATEGORY_LABELS,
    STAGE_LABELS,
    ChatAnswer,
    PrepQuestion,
    VacancyRecord,
)
from core.domains.preparation.vacancy_context import truncate_vacancy_text
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.observability import event

# Пути те же, что в декларациях `core.domains.preparation.llm` (PROMPT_PATHS); импортировать
# оттуда нельзя — модуль деклараций тянет за собой platform.llm, а тут домен.
# Расхождение ловит tests/test_prompt_path_literals.py: рефактор R (prompts/interview →
# prompts/preparation/interview) эти четыре литерала не переехал, и «Собрать темы», «Импорт»
# и оба контекста молча падали в 500/503.
_PREP_TOPICS_PROMPT = Path("prompts/preparation/interview/prep_topics.md")
_MAP_QUESTION_TOPICS_PROMPT = Path("prompts/preparation/interview/map_question_topics.md")
_PARSE_EXTERNAL_PROMPT = Path("prompts/preparation/interview/parse_external_prep.md")
_SOBES_OVERLAY_PROMPT = Path("prompts/preparation/interview/sobes_overlay.md")
# П.5c: промпт раскрытия темы из разбора реального собеса — регистрируется в llm.py как
# `prep_topic_expand` (basic tier). Лежит рядом, чтобы LlmFeature мог проверить существование.
_TOPIC_EXPAND_PROMPT = Path("prompts/preparation/interview/topic_expand.md")
_CHAT_ENVELOPE_RE = re.compile(r'"kind"\s*:\s*"(?:chat|questions)"')
_CHAT_TEXT_RE = re.compile(r'"text"\s*:\s*"((?:\\.|[^"\\])*)"')
# Жёсткий потолок вставки в sobes.tech (продуктовый лимит оверлея).
SOBES_OVERLAY_MAX_CHARS = 3900

# Маркер в user-реплике чата: короткий ярлык в UI + полный текст для кнопки «Скопировать».
EXTERNAL_TRANSCRIPT_MARKER = "<<<COPILOT_EXTERNAL_TRANSCRIPT>>>"
_VALID_PREP_CATEGORIES = frozenset({"technical", "behavioral", "case", "questions_to_ask"})
# LLM часто пишет theory/system_design (это этапы, не категории PrepQuestion) - сводим к канону.
_CATEGORY_ALIASES: dict[str, str] = {
    "technical": "technical",
    "behavioral": "behavioral",
    "case": "case",
    "questions_to_ask": "questions_to_ask",
    "theory": "technical",
    "system_design": "case",
    "systemdesign": "case",
    "live_coding": "technical",
    "livecoding": "technical",
    "business_case": "case",
    "businesscase": "case",
    "other": "technical",
    "algo": "technical",
    "algorithm": "technical",
    "algorithms": "technical",
    "coding": "technical",
    "soft": "behavioral",
    "soft_skills": "behavioral",
    "architecture": "case",
}


def format_external_transcript_message(transcript: str) -> str:
    """User-реплика парсинга: ярток для UI + полный диалог под маркером (без усечения)."""
    body = transcript.strip()
    return f"Внешняя переписка (парсинг)\n\n{EXTERNAL_TRANSCRIPT_MARKER}\n{body}"


def extract_external_transcript(content: str) -> str | None:
    """Достать полный текст внешней переписки из user-реплики, если это парсинг."""
    if EXTERNAL_TRANSCRIPT_MARKER not in content:
        return None
    _, _, rest = content.partition(EXTERNAL_TRANSCRIPT_MARKER)
    return rest.lstrip("\n") or None


def _normalize_prep_category(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    if key in _VALID_PREP_CATEGORIES:
        return key
    return "technical"


logger = logging.getLogger(__name__)

_STAGE_HINTS: dict[str, str] = {
    "screening": (
        "HR-скрининг: общие мотивации, гибкие требования (формат/ЗП/локация), "
        "проверка реальности опыта. Технические вопросы — лёгкие, проверка терминологии."
    ),
    "tech": (
        "Техничка: глубокие вопросы по основным навыкам из вакансии + резюме. "
        "Кейс/практика: реальный сценарий из продакшена под стек вакансии, проверка trade-off-ов."
    ),
    "theory": (
        "Теория: глубокие концептуальные вопросы по фундаменту стека вакансии - ключевые темы "
        "своего направления из резюме. Просят объяснить «как работает X» и «почему так», "
        "а не написать код."
    ),
    "system_design": (
        "System design: один большой кейс на проектирование системы под стек вакансии, "
        "с обсуждением масштаба, отказов, мониторинга. Технические — минимум."
    ),
    "live_coding": (
        "Live coding: пишешь код вживую при интервьюере. Алгоритмы (часто medium) плюс "
        "практическая задача под стек - распарсить, собрать пайплайн, реализовать кусок логики. "
        "Ждут чистый код, разбор сложности и edge-кейсов вслух, рабочее решение в срок."
    ),
    "business_case": (
        "Бизнес-кейс: дают продуктовую/бизнес-задачу, нужно предложить решение под свою "
        "специализацию - какой подход, какие данные, метрики и impact, риски и стоимость, как "
        "доводить до продакшена и мерить эффект. Проверяют продуктовое мышление и связь решения "
        "с бизнесом."
    ),
    "final": (
        "Финал с тимлидом / head of: стратегические вопросы про команду, roadmap, ownership, "
        "что хочешь делать, conflict resolution. Меньше код-практики, больше «как ты думаешь». "
        'Категория "case" на финале — рабочий сценарий или конфликт в команде («как поступишь, '
        "если...»), НЕ архитектурный кейс."
    ),
    "hr_final": (
        "HR-финал: ЗП, бонусы, опционы, формат, релокация, причины ухода, conflicts, "
        "ожидания. Технических — нет."
    ),
    "other": (
        "Свободный технический этап: формат заранее не известен. Готовь смешанный набор - "
        "ключевые технические вопросы по стеку, пара поведенческих, кейс под специализацию."
    ),
}

# Чеклист «за 3 часа до» по типу этапа (реалии РФ-бигтеха 2026). Статическое доменное знание,
# не дёргает LLM: рендерится вкладкой «Подготовка» и переиспользуемо ботом. Стиль —
# рубленые строки, без длинных тире, активные глаголы (CLAUDE.md, стиль владельца).
_STAGE_CHECKLISTS: dict[str, list[str]] = {
    "screening": [
        "Открой вакансию и резюме рядом, сверь стек и грейд",
        "Заготовь вилку ЗП и причину смены места в двух фразах",
        "Проверь формат - удалёнка, оформление, таймзона",
        "Сформулируй за 30 секунд кто ты и чем полезен",
        "Подготовь 3 вопроса про команду и продукт",
    ],
    "tech": [
        "Разомни пальцы - 1-2 задачи easy/medium",
        "Повтори прод-кейсы из своего стека - какие trade-off проговоришь",
        "Освежи ключевые метрики своего направления - как мерил результат",
        "Проверь среду лайвкодинга - IDE, шаринг экрана, звук",
        "Держи под рукой 2-3 числа из проектов - latency, объёмы, эффект",
    ],
    "theory": [
        "Повтори фундамент своего стека - ключевые концепции и термины",
        "Освежи теорию по стеку вакансии - ключевые темы из резюме и текста вакансии",
        "Подготовь чёткие определения ключевых метрик своего направления",
        "Проговори вслух «как работает X» по верхним темам резюме",
        "Держи 2-3 примера где теория встречалась с практикой в твоих проектах",
    ],
    "system_design": [
        "Повтори шаблон - требования, оценка нагрузки, узкие места, отказы, мониторинг",
        "Подготовь референс-архитектуру под свой стек - основные компоненты и потоки данных",
        "Заготовь вопросы на уточнение требований, не бросайся в решение сразу",
        "Продумай где деградировать - фолбэки, лимиты, стоимость",
        "Открой доску для схем, проверь что рисовать удобно",
    ],
    "live_coding": [
        "Разомни пальцы - 1-2 задачи easy/medium на время",
        "Проверь среду - IDE, шаринг экрана, звук, заготовь шаблоны",
        "Тренируй проговаривание вслух - подход, сложность, edge-кейсы",
        "Освежи типовые структуры данных и приёмы под свой язык",
        "Держи под рукой сниппеты под свой стек - парсинг, пайплайн, типовые вызовы",
    ],
    "business_case": [
        "Заготовь рамку - задача, решение, данные, метрика, риск, стоимость",
        "Повтори как считаешь impact и продуктовые метрики, держи примеры с цифрами",
        "Продумай где твоё направление реально решает задачу, а где нет - честные ограничения",
        "Подготовь вопросы на уточнение задачи, не бросайся в решение сразу",
        "Освежи прод-кейсы где доводил решение до эффекта в деньгах или метриках",
    ],
    "final": [
        "Сформулируй чем хочешь заниматься и куда расти в горизонте года",
        "Заготовь 1-2 истории про ownership и разрешённый конфликт",
        "Освежи продукт и команду компании - роадмап, вызовы",
        "Подготовь вопросы тимлиду про процессы, зону ответственности, рост",
        "Держи вилку ЗП и условия - финал часто про оффер",
    ],
    "hr_final": [
        "Зафиксируй точную вилку - минимум, желаемое, на руки",
        "Проговори причины ухода нейтрально, без негатива",
        "Уточни вопросы по офферу - бонусы, опционы, ДМС, формат, отпуск",
        "Подготовь сроки выхода и нотис",
        "Не называй цифру первым, если можно дождаться предложения",
    ],
    "other": [
        "Сверь вакансию и резюме, выпиши вероятные форматы этапа",
        "Держи прод-кейсы из своего стека наготове",
        "Разомнись на 1-2 задачах и проговори пару прод-историй",
        "Проверь среду созвона - звук, шаринг, доска",
        "Подготовь 3 вопроса про команду, процессы и роадмап",
    ],
}


# Опорный каркас — статический список шагов, держать в голове на любой похожий вопрос этого
# формата. Не LLM: рендерится маленькой карточкой над списком вопросов, ничего не стоит.
# Калька с универсального каркаса, которым владелец реально пользовался при подготовке во внешнем
# чате — не выдумано с нуля.
_STAGE_FRAMEWORKS: dict[str, list[str]] = {
    "system_design": [
        "Уточнить масштаб и требования (объём, модальность, задержка/цена)",
        "Разбить процесс на этапы (сбор → фильтрация → обработка → контроль качества → выдача)",
        "Назвать компонент и место хранения на каждом этапе",
        "Проговорить контроль качества",
        "Проговорить масштабирование/экономию бюджета",
        "Закончить trade-off'ом",
    ],
    "business_case": [
        "Задача - что решаем и для кого",
        "Решение - подход на уровне идеи",
        "Данные - что нужно для решения",
        "Метрика - как измерить успех",
        "Риск - что может пойти не так",
        "Стоимость/impact - окупается ли",
    ],
    "final": [
        "Контекст - в чём была ситуация",
        "Варианты - что рассматривал",
        "Выбор - что сделал и почему",
        "Результат - как измерил эффект",
    ],
}


def framework_for_stage(stage: str) -> list[str]:
    """Опорный каркас ответа под формат этапа (пусто, если формату каркас не нужен)."""
    return list(_STAGE_FRAMEWORKS.get(stage, []))


def checklist_for_stage(stage: str, profile: CompanyProfile | None = None) -> list[str]:
    """Чеклист «за 3 часа до» под этап + доп. пункты под формат компании (если профиль найден).

    Профиль меняет состав подготовки: к базовым пунктам добавляются специфичные для
    формата компании на этом этапе (алгосекция Яндекса, on-prem Сбера, live coding Т-Банка…).
    """
    base = list(_STAGE_CHECKLISTS.get(stage, []))
    if profile is not None:
        base.extend(profile.stage_tips.get(stage, []))
    return base


def _build_company_block(stage: str, profile: CompanyProfile | None) -> str:
    """Блок «профиль компании» в системный промпт — формат этапа у конкретной компании."""
    if profile is None:
        return ""
    note = profile.stage_notes.get(stage, "")
    note_line = f"\nФормат этапа в «{profile.name}»: {note}" if note else ""
    return (
        f"\n## Профиль компании: {profile.name}\n\n"
        f"{profile.summary}{note_line}\n\n"
        f"Учитывай этот формат: вопросы и кейсы подгоняй под то, как «{profile.name}» реально "
        "проводит этот этап (тип секций, акценты, стек).\n"
    )


def _build_focus_block(focus_topics: list[str] | None) -> str:
    """Блок «фокус по слабым темам из разбора прошлого собеса» (→ JS-4).

    Слабые темы приходят из разбора собеса; на них генерация делает упор — больше вопросов и
    кейсов именно по ним, чтобы повторение закрывало реальные провалы прошлого этапа.
    """
    topics = [t.strip() for t in (focus_topics or []) if t and t.strip()]
    if not topics:
        return ""
    lines = "\n".join(f"- {t}" for t in topics[:12])
    return (
        "\n## Фокус: слабые темы из разбора прошлого собеса\n\n"
        "Кандидат уже проходил собес и просел на этих темах. Сделай на них особый упор - "
        "добавь больше вопросов и кейсов именно по ним:\n"
        f"{lines}\n"
    )


# L-49: Pipeline-сплит generate_prep_questions — «что спросят» (technical/behavioral/case)
# параллельно «что спросить самому» (questions_to_ask), общий system/user, разный фокус-хвост
# (тот же приём, что `_DIAGNOSIS_FOCUS`/`_ACTIONS_FOCUS` в core.domains.market.situation).
_ANSWER_FOCUS = """

ЭТОТ ВЫЗОВ — только категории "technical", "behavioral", "case" (вопросы, которые ЗАДАДУТ
кандидату). Категорию "questions_to_ask" не генерируй - её пишет отдельный параллельный вызов."""

_ASK_THEM_FOCUS = """

ЭТОТ ВЫЗОВ — только категория "questions_to_ask" (вопросы, которые кандидат должен задать
компании). Остальные категории не генерируй - их пишет отдельный параллельный вызов."""


async def _build_prep_system_parts(
    stage: str,
    profile: CompanyProfile | None = None,
    focus_topics: list[str] | None = None,
    context_block: str = "",
    *,
    account_id: int | None = None,
) -> tuple[str, str]:
    """L-11: (статичный prefix с резюме/правилами, dynamic_tail с этапом/контекстом)."""
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    instructions = load_instructions()
    resume = load_resume(data=resume_data)
    identity = load_candidate_identity(data=resume_data)
    stage_label = STAGE_LABELS.get(stage, stage)
    stage_hint = _STAGE_HINTS.get(stage, "")
    company_block = _build_company_block(stage, profile)
    focus_block = _build_focus_block(focus_topics)

    dynamic = f"""## Контекст этапа

Этап: {stage_label}.
{stage_hint}
{company_block}{focus_block}{context_block}""".rstrip()

    static = f"""Ты — карьерный коуч, готовишь конкретного кандидата ({identity}) к собеседованию.

## Резюме кандидата

{resume}

## Стратегические предпочтения и приоритеты кандидата

{instructions}

## Что ты делаешь

На входе — текст вакансии. На выходе — набор вопросов, которые ВЕРОЯТНО зададут на этом этапе,
с учётом профиля кандидата и стека вакансии. Никаких общих советов «расскажите о себе» — только
конкретные, привязанные к вакансии и к опыту кандидата. **К каждому вопросу — готовый ответ**,
который кандидат может почти дословно воспроизвести на собеседовании.

Категории:
- "technical": конкретные вопросы по стеку из вакансии и резюме кандидата (языки, фреймворки, инфра, безопасность).
- "behavioral": ситуации из реального опыта кандидата — ownership, conflicts, ошибки, рост.
- "case": продакшн-кейс или system design под этот стек (на screening пропусти или сократи).
- "questions_to_ask": умные вопросы, которые САМ кандидат должен задать компании, чтобы прощупать
  команду, roadmap, риски.

Минимум-максимум на этап:
- screening: technical 3, behavioral 2, case 1, questions_to_ask 3 (всего ~9).
- tech: technical 5, behavioral 2, case 2, questions_to_ask 3 (всего ~12).
- theory: technical 6, behavioral 1, case 1, questions_to_ask 2 (всего ~10, упор на «как работает X»).
- system_design: technical 2, case 4, questions_to_ask 3 (всего ~9, без behavioral).
- live_coding: technical 4, case 3, behavioral 1, questions_to_ask 2 (всего ~10, technical/case — задачи на код).
- business_case: technical 1, behavioral 1, case 4, questions_to_ask 2 (всего ~8, case — продуктовые задачи).
- final: technical 0, behavioral 4, case 2, questions_to_ask 3 (всего ~9, case — рабочий сценарий, не архитектура).
- hr_final: technical 0, behavioral 2, case 0, questions_to_ask 5 (всего ~7).
- other: technical 4, behavioral 2, case 2, questions_to_ask 3 (всего ~11).

## Правила вывода

1. Верни СТРОГО валидный JSON по схеме:
   {{
     "questions": [
       {{"category": "technical|behavioral|case|questions_to_ask", "text": "...", "hint": "...", "answer": "..."}},
       ...
     ]
   }}
2. Никакого текста до или после JSON. Без markdown-обёртки.
3. Поле "text" — собственно вопрос на русском.
4. Поле "hint" — короткая (1-2 предложения) подсказка кандидату: на что обратить внимание,
   какой опыт из резюме привести, какой trade-off проговорить. НЕ ответ — направление.
5. Поле "answer" — **готовый ответ**, который кандидат может воспроизвести почти дословно. Стиль
   и структура зависят от формата этапа, простой человечный язык без канцелярита и без маркеров
   автогенерации (никаких «как AI-ассистент я бы…», «в заключение», «важно отметить») — во всех
   случаях:
   - **Устные форматы по умолчанию** (`screening`, `tech`, `theory`, `final`, `hr_final`, `other`):
     НИКАКОГО кода и код-блоков, НИКАКИХ формул и математики (`$...$`). Длина рассчитана на 30-60
     секунд устной речи (примерно 60-110 слов). На сложных концепциях — ровно одна простая
     аналогия-сравнение, не разжёвывай её дольше 1-2 предложений. Ответ должен быть дословно
     произносим — так, как кандидат скажет вслух, а не как выглядит документация.
   - **`live_coding`**: рабочий код в код-блоке с языком (```язык) обязателен, плюс короткий
     устный комментарий вокруг него — сложность, edge-кейсы. Без формул.
   - **`system_design`**: без кода и формул. Схема в mermaid-блоке (```mermaid), ответ идёт по
     каркасу из 6 шагов (масштаб/требования → этапы процесса → компоненты и хранение → контроль
     качества → масштабирование/бюджет → trade-off) и обязательно заканчивается trade-off'ом.
   - **`business_case`**: без кода и формул. Структура: задача → решение → данные → метрика →
     риск → стоимость, заканчивай риском или оговоркой.
   - **`final`**: без кода и формул. Категория "case" здесь — НЕ архитектурное проектирование, а
     рабочий/лидерский сценарий («как поступишь, если...»). Упор на behavioral и планирование, не
     на технику. Обязательно опирайся на реальные обязанности/задачи из текста вакансии (раздел
     «Текст вакансии» ниже) при формулировке behavioral- и case-вопросов — вопрос должен звучать в
     терминах ИМЕННО этих обязанностей (например, если в вакансии явно написано «формирование
     команды» — вопрос про формирование команды, не абстрактный «расскажи о лидерском опыте»),
     не в терминах общих менеджерских клише.
   - Выделяй **жирным** ключевые термины и числа, на которые стоит сделать упор при ответе.
   - Длина — 2-4 абзаца (для кейсов больше, устные форматы короче — см. лимит слов выше), без
     воды. Каждое предложение несёт смысл. Ответ должен звучать так, как будто его говорит опытный
     {identity} (владелец резюме), а не как выдержка из документации.
6. Не дублируй вопросы.
7. Технические вопросы — конкретные («как бы вы спроектировали X под этот стек»), не «знаете ли вы Y».
8. Категорию "case" не выдумывай, если этап её не требует (см. лимиты выше) — просто пропусти.
9. Не используй `---`, таблицы, блоки цитат `>`, ссылки `[text](url)` — фронт (`MarkdownView`) их
   не рендерит. Из разрешённого: заголовки, списки, **жирный**, `==хайлайт==`, код-блоки,
   ```mermaid, `$формулы$` (формулы — не для устных форматов, см. пункт 5).
"""
    return static, dynamic


def _build_prep_user_prompt(record: VacancyRecord) -> str:
    title = record.title or "?"
    company = record.company or "?"
    salary = record.salary_text or "не указано"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=8000)
    score = record.score
    overall = score.overall_score if score else "?"
    verdict = score.one_line_verdict if score else ""

    return f"""## Вакансия

Компания: {company}
Позиция: {title}
Зарплата (вакансия): {salary}
Скор: {overall}/100
Вердикт скорера: {verdict}

### Текст вакансии

{text}

Сгенерируй список вопросов под этап (см. инструкции). Ответ — по схеме questions[].
"""


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _parse_question_item(item: Any) -> PrepQuestion | None:
    """Один элемент массива "questions" → `PrepQuestion` (PREP-3: переиспользуется и генерацией
    полного набора, и парсингом пачки из чата).

    Категории-синонимы (theory/system_design/…) нормализуем до канона PrepCategory - иначе LLM
    из внешнего парсинга массово отваливается на валидации.
    """
    if not isinstance(item, dict):
        return None
    data = dict(item)
    data["category"] = _normalize_prep_category(data.get("category"))
    text = str(data.get("text") or "").strip()
    if len(text) > 2000:
        data["text"] = text[:2000]
    # LLM иногда шлёт explicit null - дефолты Pydantic срабатывают только при отсутствии ключа.
    for key in ("hint", "answer"):
        if data.get(key) is None:
            data[key] = ""
    try:
        return PrepQuestion(**data)
    except Exception as exc:  # noqa: BLE001 — битый вопрос пропускаем, не валим набор
        logger.warning("Битый вопрос пропущен: %s (%s)", item, exc)
        return None


def _parse_questions(raw: str) -> list[PrepQuestion]:
    """Ручной разбор JSON (чат / legacy-пути). Генерация набора — через structured."""
    data = json.loads(_strip_json_fence(raw))
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM не вернул поле 'questions' со списком")
    questions = [q for item in items if (q := _parse_question_item(item)) is not None]
    if not questions:
        raise ValueError("Список вопросов пуст после валидации")
    return questions


# L-12: схема structured-выхода generate_prep_questions (без outcome/topic — их ставит продукт).
class _PrepQuestionOut(BaseModel):
    category: Literal["technical", "behavioral", "case", "questions_to_ask"] = "technical"
    text: str = Field(min_length=3, max_length=2000)
    hint: str = ""
    answer: str = ""


class _PrepQuestionsOut(BaseModel):
    questions: list[_PrepQuestionOut] = Field(min_length=1)


def _questions_from_structured(parsed: _PrepQuestionsOut) -> list[PrepQuestion]:
    questions = [
        q for item in parsed.questions if (q := _parse_question_item(item.model_dump())) is not None
    ]
    if not questions:
        raise ValueError("Список вопросов пуст после валидации")
    return questions


async def _prep_pipeline(
    record: VacancyRecord,
    stage: str,
    profile: CompanyProfile | None,
    focus_topics: list[str] | None,
    context_block: str,
    *,
    account_id: int,
) -> Pipeline:
    """DAG подготовки: «что спросят» ∥ «что спросить самому» — общий system/user,
    разный фокус-хвост (см. `_ANSWER_FOCUS`/`_ASK_THEM_FOCUS`)."""
    system, dynamic_base = await _build_prep_system_parts(
        stage, profile, focus_topics, context_block, account_id=account_id
    )
    user = _build_prep_user_prompt(record)

    async def _call(focus_tail: str) -> list[PrepQuestion]:
        # L-12: A-07 structured — без ручного JSON/fence и лишних retry на синтаксис.
        parsed = await ports.llm().structured(
            "prep",
            system=system,
            dynamic_tail=dynamic_base + focus_tail,
            user=user,
            schema=_PrepQuestionsOut,
            temperature=0.5,
        )
        return _questions_from_structured(parsed)

    async def answers_step(_ctx: Any) -> list[PrepQuestion]:
        return await _call(_ANSWER_FOCUS)

    async def ask_them_step(_ctx: Any) -> list[PrepQuestion]:
        return await _call(_ASK_THEM_FOCUS)

    return Pipeline(
        [
            Step("answers", answers_step, required=False, default_factory=list),
            Step("ask_them", ask_them_step, required=False, default_factory=list),
        ],
        name="prep_questions",
    )


async def generate_prep_questions(
    record: VacancyRecord,
    stage: str,
    profile: CompanyProfile | None = None,
    focus_topics: list[str] | None = None,
    *,
    account_id: int,
) -> list[PrepQuestion]:
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    context = await gather_prep_context(record.vacancy_id or "", stage, account_id=account_id)
    pipeline = await _prep_pipeline(
        record, stage, profile, focus_topics, context.render(), account_id=account_id
    )
    try:
        parts = await pipeline.run()
    except PipelineError as exc:
        cause = exc.cause if isinstance(exc.cause, Exception) else exc
        raise LlmError(f"Не удалось собрать вопросы: {cause}") from exc
    answers_n = len(parts.get("answers", []))
    ask_them_n = len(parts.get("ask_them", []))
    questions = [*parts.get("answers", []), *parts.get("ask_them", [])]
    if not questions:
        raise LlmError("Не удалось собрать вопросы: обе части пустые")
    empty_parts = [name for name, n in (("answers", answers_n), ("ask_them", ask_them_n)) if n == 0]
    event(
        logger,
        "LLM",
        "подготовка вопросов собрана: %d (answers=%d, ask_them=%d)",
        len(questions),
        answers_n,
        ask_them_n,
        vacancy_id=record.vacancy_id,
        stage=stage,
        total=len(questions),
        answers=answers_n,
        ask_them=ask_them_n,
        empty_parts=empty_parts,
        level=logging.WARNING if empty_parts else logging.INFO,
    )
    return questions


async def generate_prep_questions_events(
    record: VacancyRecord,
    stage: str,
    profile: CompanyProfile | None = None,
    focus_topics: list[str] | None = None,
    *,
    account_id: int,
) -> AsyncIterator[dict[str, Any]]:
    """Тот же расчёт, но части (`answers`/`ask_them`) отдаются по мере готовности."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    context = await gather_prep_context(record.vacancy_id or "", stage, account_id=account_id)
    pipeline = await _prep_pipeline(
        record, stage, profile, focus_topics, context.render(), account_id=account_id
    )

    answers: list[PrepQuestion] = []
    ask_them: list[PrepQuestion] = []

    async for pipeline_event in pipeline.stream():
        if pipeline_event.type == "step_start":
            yield {
                "type": "status",
                "stage": pipeline_event.step,
                "label": "Собираю вопросы"
                if pipeline_event.step == "answers"
                else "Собираю вопросы к HR",
            }
        elif pipeline_event.type == "step_done" and pipeline_event.step == "answers":
            answers = pipeline_event.data or []
            yield {"type": "answers", "questions": [q.model_dump(mode="json") for q in answers]}
        elif pipeline_event.type == "step_done" and pipeline_event.step == "ask_them":
            ask_them = pipeline_event.data or []
            yield {"type": "ask_them", "questions": [q.model_dump(mode="json") for q in ask_them]}
        elif pipeline_event.type == "error" and pipeline_event.step in ("answers", "ask_them"):
            yield {
                "type": "part_error",
                "stage": pipeline_event.step,
                "message": pipeline_event.message,
            }
        elif pipeline_event.type == "done":
            questions = [*answers, *ask_them]
            if not questions:
                raise LlmError("Не удалось собрать вопросы: обе части пустые")
            yield {
                "type": "done",
                "questions": [q.model_dump(mode="json") for q in questions],
            }


# ---- чат подготовки (вкладка «Технички», режим «Подготовка») ----

_PREP_CHAT_SYSTEM_TEMPLATE = """Ты — карьерный коуч, помогаешь владельцу ({{CANDIDATE_IDENTITY}}) готовиться к собеседованию.

Контекст вакансии, этап и история подготовки (вопросы+ответы) уже в системном промпте. Сейчас
владелец ведёт свободный чат: может попросить сгенерировать ещё пачку вопросов с ответами для
этого же этапа, объяснить подробнее тему, дать встречный вопрос, если что-то непонятно, или
уточнить trade-off.

## Формат вывода — строго JSON, без текста до/после и без markdown-обёртки

{{"kind": "chat" | "questions", "text": "...", "topic": "..." или null, "questions": [...]}}

- "kind" = "questions" — когда сообщение владельца читается как просьба ещё вопросов/пачки по
  теме («дай ещё пачку», «вопросы по Kafka», «что ещё могут спросить про X»). Во всех остальных
  случаях (разбор термина, «объясни проще», встречный вопрос, разбор вставленного текста
  вакансии и т.п.) — "chat".
- "text" при "kind"="questions" — КОРОТКОЕ подтверждение на русском («Добавил пачку «{{topic}}» —
  N вопросов, они выше в списке»). НЕ дублируй вопросы текстом здесь — они уйдут в "questions".
  При "kind"="chat" — обычный ответ по правилам ниже.
- "topic" — только при "kind"="questions": 2-4 слова, короткий ярлык пачки («Kafka/Flink»,
  «Big Data хранилища»). Иначе null.
- "questions" — только при "kind"="questions": новые вопросы той же схемы, что при генерации
  подготовки — [{{"category": "technical|behavioral|case|questions_to_ask", "text": "...",
  "hint": "...", "answer": "..."}}]. НЕ повторяй вопросы, уже сгенерированные ранее (см. блок
  «Уже сгенерированные вопросы+ответы» в контексте ниже) и вопросы из прошлых пачек этого же
  чата. При "kind"="chat" — пустой список.

## Правила

1. Отвечай на русском, простым человечным языком — без канцелярита, без маркеров автогенерации
   («как AI-ассистент…», «в заключение», «важно отметить»).
2. Пачка вопросов ("kind"="questions") — с готовыми ответами, в схеме "questions" из конверта выше.
3. Стиль и структура ответа/пачки зависят от формата этапа (передан в контексте ниже):
   - Устные форматы по умолчанию (`screening`, `tech`, `theory`, `final`, `hr_final`, `other`):
     БЕЗ кода и код-блоков, БЕЗ формул (`$...$`). Простой человечный язык, длина под 30-60 секунд
     устной речи. На сложных местах — ровно одна простая аналогия, 1-2 предложения.
   - `live_coding`: код в код-блоке с языком обязателен, короткий устный комментарий вокруг него.
     Без формул.
   - `system_design`: без кода и формул, mermaid-схема (```mermaid) + каркас из 6 шагов, заканчивай
     trade-off'ом.
   - `business_case`: без кода и формул, структура задача→решение→данные→метрика→риск→стоимость.
   - `final`: без кода и формул, "case" здесь — рабочий/лидерский сценарий, не архитектурный кейс.
     Опирайся на реальные обязанности из текста вакансии, не на общие менеджерские клише.
4. Выделяй **жирным** ключевые термины и числа — на них владелец делает упор при ответе.
5. Не используй `---`, таблицы, блоки цитат `>`, ссылки `[text](url)` — фронт (`MarkdownView`) их
   не рендерит. Из разрешённого: заголовки, списки, **жирный**, `==хайлайт==`, код-блоки,
   ```mermaid, `$формулы$` (не для устных форматов, см. пункт 3).
6. Если вопрос владельца не про подготовку, а про тему — объясняй так, как объяснил бы опытному
   коллеге сам {{CANDIDATE_IDENTITY}}: по делу, без воды, с примерами из прод-опыта.
7. Не пересказывай весь контекст вакансии обратно — владелец его уже видит.

## Владелец вставил чужую переписку (отдельного режима «Внешний ИИ» больше нет)

Сообщение владельца может быть не вопросом, а **вставленным куском переписки**: диалог с другим
ИИ-чатом, беседа с рекрутёром, свои заметки, распознанный скриншот. Узнаётся по форме: несколько
реплик подряд, подписи говорящих («Вопрос:/Ответ:», «Я:», «ChatGPT:», «HR:»), готовые пары
вопрос-ответ, отсутствие прямой просьбы к тебе.

Сначала реши, что это:

- **Продолжение текущей подготовки** — вставка развивает то, о чём вы уже говорили в этом чате
  (см. «История чата подготовки»): уточнение к твоему прошлому ответу, разбор той же темы у
  другой модели, дописанный владельцем черновик ответа. Тогда "kind"="chat": ответь по существу —
  что там верно, что мимо, чего не хватает под ЭТУ вакансию и этап. Не пересказывай вставку.
- **Сторонний материал с готовыми парами вопрос-ответ** — прогнанные где-то ещё вопросы, которые
  надо занести в подготовку. Тогда "kind"="questions": вытащи ВСЕ содержательные пары (теория,
  код, design, behavioral — даже если этап в UI другой), ответы сожми до сути в своём стиле,
  проверь их правильность под резюме и вакансию. Не дублируй по смыслу вопросы из блока
  «Уже сгенерированные вопросы+ответы». "topic" — 2-4 слова про источник/тему пачки.
  В "text" — короткое подтверждение («Занёс N вопросов из переписки»).
- **Смешанный случай** — есть и готовые пары, и вопрос владельца к тебе: приоритет у вопроса
  ("kind"="chat"), но в ответе явно скажи, что нашёл готовые пары и предложи занести их.

Если это обычное сообщение владельца, а не вставка, — этот блок не применяется.
"""


def _build_pack_block(pack_content: str | None) -> str:
    """UX2-7.3: собранный бриф подготовки — фоновый контекст чата, чтобы LLM не повторяла
    уже закрытые в нём темы/вопросы без явной просьбы владельца."""
    text = (pack_content or "").strip()
    if not text:
        return ""
    return (
        "\n## Собранный бриф подготовки (что спросят, слабые темы, фидбек рекрутёра)\n\n"
        f"{text}\n\n"
        "Владелец уже читал этот бриф - не пересказывай его заново и не повторяй уже закрытые в "
        "нём темы/вопросы, если он сам не попросит вернуться к ним.\n"
    )


async def _build_prep_chat_system(
    record: VacancyRecord,
    stage: str,
    profile: CompanyProfile | None,
    focus_topics: list[str] | None,
    prep_questions: list[PrepQuestion] | None,
    context_block: str = "",
    pack_content: str | None = None,
    *,
    account_id: int,
) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    instructions = load_instructions()
    resume = load_resume(data=resume_data)
    prep_chat_intro = _PREP_CHAT_SYSTEM_TEMPLATE.replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )
    stage_label = STAGE_LABELS.get(stage, stage)
    stage_hint = _STAGE_HINTS.get(stage, "")
    company_block = _build_company_block(stage, profile)
    focus_block = _build_focus_block(focus_topics)
    pack_block = _build_pack_block(pack_content)

    # Превью уже сгенерированных вопросов+ответов — чтобы LLM не повторялась и опиралась на то,
    # что владелец уже видел. Берём первые 8 (всё равно LLM обрежет, но даём ориентир).
    prep_block = ""
    if prep_questions:
        lines: list[str] = []
        for i, q in enumerate(prep_questions[:8], 1):
            lines.append(f"{i}. [{q.category}] {q.text}")
            if q.answer.strip():
                lines.append(f"   Ответ: {q.answer.strip()[:400]}")
        prep_block = (
            "\n## Уже сгенерированные вопросы+ответы (не повторяй их)\n\n" + "\n".join(lines) + "\n"
        )

    return f"""{prep_chat_intro}

## Резюме кандидата

{resume}

## Стратегические предпочтения и приоритеты

{instructions}

## Контекст этапа

Этап: {stage_label}.
{stage_hint}{company_block}{focus_block}{pack_block}{prep_block}{context_block}
"""


def _build_prep_chat_user(record: VacancyRecord, message: str, history_text: str) -> str:
    title = record.title or "?"
    company = record.company or "?"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=4000)
    history_part = (
        f"\n## История чата подготовки\n\n{history_text}\n" if history_text.strip() else ""
    )
    return f"""## Вакансия

Компания: {company}
Позиция: {title}

### Текст вакансии

{text}
{history_part}
## Сообщение владельца

{message}
"""


def _looks_like_chat_envelope(raw: str) -> bool:
    """Сырой ответ похож на JSON-конверт kind/text — его нельзя показывать владельцу как есть."""
    return bool(_CHAT_ENVELOPE_RE.search(raw))


def _extract_text_field(raw: str) -> str | None:
    """Достать поле text из конверта даже при битом JSON (частичный escape / обрезанный хвост)."""
    m = _CHAT_TEXT_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(f'"{m.group(1)}"').strip() or None
    except json.JSONDecodeError:
        return m.group(1).replace("\\n", "\n").replace('\\"', '"').strip() or None


def _parse_chat_answer(raw: str) -> ChatAnswer:
    """Строгий JSON-конверт chat/questions чата подготовки.

    Битый JSON: пытаемся вытащить `text`; сырой конверт `{"kind":...}` в чат не кладём —
    иначе артефакт разметки утекает в UI.
    """
    stripped = _strip_json_fence(raw)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        extracted = _extract_text_field(stripped)
        if extracted:
            return ChatAnswer(kind="chat", text=extracted)
        if _looks_like_chat_envelope(stripped):
            logger.warning("prep chat: битый JSON-конверт, text не извлечён")
            return ChatAnswer(
                kind="chat",
                text="Не удалось разобрать ответ. Напиши ещё раз или переформулируй.",
            )
        return ChatAnswer(kind="chat", text=raw.strip())
    if not isinstance(data, dict):
        extracted = _extract_text_field(stripped)
        if extracted:
            return ChatAnswer(kind="chat", text=extracted)
        if _looks_like_chat_envelope(stripped):
            return ChatAnswer(
                kind="chat",
                text="Не удалось разобрать ответ. Напиши ещё раз или переформулируй.",
            )
        return ChatAnswer(kind="chat", text=raw.strip())

    text = str(data.get("text") or "").strip()
    topic_raw = data.get("topic")
    topic = topic_raw.strip() if isinstance(topic_raw, str) and topic_raw.strip() else None

    if data.get("kind") == "questions":
        items = data.get("questions")
        questions = (
            [q for item in items if (q := _parse_question_item(item)) is not None]
            if isinstance(items, list)
            else []
        )
        if questions:
            # PREP-4: проставляем ярлык пачки на каждый вопрос — фронт группирует подряд идущие
            # карточки с одинаковым topic под заголовком, персист (append_prep_questions) сохраняет
            # поле как есть (model_dump).
            for q in questions:
                q.topic = topic
            return ChatAnswer(
                kind="questions",
                text=text or f"Добавил пачку вопросов - {len(questions)} шт.",
                topic=topic,
                questions=questions,
            )
        # LLM объявила пачку, но не дала ни одного валидного вопроса — деградируем в chat-ответ.
        logger.warning("prep chat: kind=questions без валидных вопросов, деградирую в chat")

    if text:
        return ChatAnswer(kind="chat", text=text, topic=topic)
    extracted = _extract_text_field(stripped)
    if extracted:
        return ChatAnswer(kind="chat", text=extracted, topic=topic)
    if _looks_like_chat_envelope(stripped):
        logger.warning("prep chat: конверт без usable text")
        return ChatAnswer(
            kind="chat",
            text="Не удалось разобрать ответ. Напиши ещё раз или переформулируй.",
        )
    return ChatAnswer(kind="chat", text=raw.strip())


@lru_cache(maxsize=8)
def _load_prompt_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Промпт не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


async def generate_vacancy_prep_topics(
    record: VacancyRecord,
    stage: str,
) -> list[str]:
    """LLM: темы, которые могут спросить по вакансии на этапе — для «Готовность по темам»."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    system = _load_prompt_file(_PREP_TOPICS_PROMPT)
    stage_label = STAGE_LABELS.get(stage, stage)
    title = record.title or "?"
    company = record.company or "?"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=4000)
    user = f"""Этап: {stage_label}
Компания: {company}
Позиция: {title}

### Текст вакансии

{text}
"""
    raw = await ports.llm().complete("prep", system=system, user=user, temperature=0.3)
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM вернула не-JSON для тем подготовки: {exc}") from exc
    items = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM не вернула поле topics")
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name[:200])
    if not out:
        raise ValueError("Список тем пуст")
    return out


async def expand_prep_topic(
    topic: str,
    record: VacancyRecord,
    stage: str,
) -> str:
    """LLM: короткая шпаргалка по теме (что входит, как обычно отвечают).

    П.5c: stateless-раскрытие темы из разбора реального собеса по клику в блоке «Темы».
    Basic-tier (GPT-5.6 Luna) — дёшево и быстро; кэшируется через общий llm_result_cache.
    """
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Не передана тема для раскрытия")
    system = _load_prompt_file(_TOPIC_EXPAND_PROMPT)
    stage_label = STAGE_LABELS.get(stage, stage)
    title = record.title or "?"
    company = record.company or "?"
    text = truncate_vacancy_text(record.vacancy_text or "", limit=3000)
    user = f"""Тема: {topic}
Этап: {stage_label}
Компания: {company}
Позиция: {title}

### Текст вакансии

{text}
"""
    raw = await ports.llm().complete("prep_topic_expand", system=system, user=user, temperature=0.3)
    markdown = (raw or "").strip()
    if not markdown:
        raise ValueError("LLM вернула пустой ответ для раскрытия темы")
    return markdown


class _TopicMapOut(BaseModel):
    """Структурированный ответ маппинга вопроса на каталог тем."""

    topics: list[str] = Field(default_factory=list)


def _match_hint_to_catalog(hint: str | None, catalog: list[str]) -> list[str]:
    """Точное/без регистра совпадение ярлыка вопроса с каталогом - без LLM."""
    if not hint or not catalog:
        return []
    needle = hint.strip().casefold()
    if not needle:
        return []
    for name in catalog:
        if name.strip().casefold() == needle:
            return [name]
    return []


async def map_question_to_prep_topics(
    question_text: str,
    catalog: list[str],
    *,
    hint_topic: str | None = None,
    answer_excerpt: str | None = None,
) -> list[str]:
    """Сопоставить раскрытый вопрос с темами каталога (фон, extract-тир).

    Сначала пробуем точный матч `hint_topic`; иначе LLM выбирает 1–3 имени из каталога.
    """
    cleaned_catalog: list[str] = []
    seen: set[str] = set()
    for raw in catalog:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned_catalog.append(name[:200])
    if not cleaned_catalog:
        return []

    exact = _match_hint_to_catalog(hint_topic, cleaned_catalog)
    if exact:
        return exact

    q = (question_text or "").strip()
    if not q:
        return []
    if not get_settings().openrouter_api_key:
        # Без ключа - мягкая деградация: ярлык пачки, если он в каталоге, иначе пусто.
        return []

    system = _load_prompt_file(_MAP_QUESTION_TOPICS_PROMPT)
    catalog_lines = "\n".join(f"- {t}" for t in cleaned_catalog)
    answer_block = (answer_excerpt or "").strip()
    user = f"""## Каталог тем

{catalog_lines}

## Вопрос

{q[:2000]}
"""
    if answer_block:
        user += f"\n## Фрагмент ответа\n\n{answer_block[:1500]}\n"
    if hint_topic and hint_topic.strip():
        user += f"\nЯрлык пачки (подсказка, не обязан совпадать с каталогом): {hint_topic.strip()[:200]}\n"

    try:
        # Фича `question_match`: тот же промпт (map_question_topics.md) и тот же дешёвый тир.
        # Раньше звалось как `prep` с ручным tier="extract" — тир вернулся в декларацию.
        result = await ports.llm().structured(
            "question_match",
            system=system,
            user=user,
            schema=_TopicMapOut,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001
        logger.exception("map_question_to_prep_topics: LLM упал")
        return []

    allowed = {t.casefold(): t for t in cleaned_catalog}
    out: list[str] = []
    for raw in result.topics:
        name = (raw or "").strip()
        canon = allowed.get(name.casefold())
        if canon and canon not in out:
            out.append(canon)
        if len(out) >= 3:
            break
    return out


async def parse_external_prep_chat(
    record: VacancyRecord,
    transcript: str,
    *,
    stage: str = "tech",
    existing_questions: list[PrepQuestion] | None = None,
) -> ChatAnswer:
    """Парсинг внешней переписки с LLM → пачка вопросов с укороченными ответами."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")
    system = _load_prompt_file(_PARSE_EXTERNAL_PROMPT)
    existing = existing_questions or []
    already = "\n".join(f"- {q.text}" for q in existing[:80]) or "(пока пусто)"
    title = record.title or "?"
    company = record.company or "?"
    stage_label = STAGE_LABELS.get(stage, stage)
    user = f"""Вакансия: {company} - {title}
Этап в UI (только контекст, НЕ фильтр тем): {stage_label}
Во внешней переписке извлекай ВСЕ отработанные Q&A - теория/код/design/behavioral,
даже если этап в UI другой.

## Уже есть в подготовке (не дублируй по смыслу)

{already}

## Внешняя переписка

{transcript.strip()}
"""
    # Больше выходных токенов: 10-20 вопросов с короткими ответами не должны обрезаться.
    raw = await ports.llm().complete(
        "prep",
        system=system,
        user=user,
        temperature=0.2,
        max_tokens=12_288,
    )
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        extracted = _extract_text_field(_strip_json_fence(raw))
        return ChatAnswer(
            kind="chat",
            text=extracted or "Не удалось разобрать переписку. Вставь фрагмент с явными Q&A.",
        )
    if not isinstance(data, dict):
        return ChatAnswer(kind="chat", text="Не удалось разобрать переписку.")
    topic_raw = data.get("topic")
    topic = topic_raw.strip() if isinstance(topic_raw, str) and topic_raw.strip() else None
    items = data.get("questions")
    questions = (
        [q for item in items if (q := _parse_question_item(item)) is not None]
        if isinstance(items, list)
        else []
    )
    if not questions:
        return ChatAnswer(
            kind="chat",
            text="В переписке не нашёл новых пар вопрос-ответ для подготовки.",
        )
    for q in questions:
        if topic and not q.topic:
            q.topic = topic
    return ChatAnswer(
        kind="questions",
        text=f"Распарсил {len(questions)} вопросов из внешней переписки.",
        topic=topic,
        questions=questions,
    )


async def answer_prep_chat(
    record: VacancyRecord,
    message: str,
    history: list[dict[str, str]],
    *,
    stage: str = "tech",
    account_id: int,
    profile: CompanyProfile | None = None,
    focus_topics: list[str] | None = None,
    prep_questions: list[PrepQuestion] | None = None,
    pack_content: str | None = None,
    images: Sequence[ports.ImageInput] = (),
) -> ChatAnswer:
    """Ответ LLM в чат подготовки: обычная реплика ИЛИ новая пачка вопросов-карточек.
    История — реплики user/assistant (без vacancy-контекста, он уже в system-промпте).

    images (Э3-1, план chat_image_attachments) — картинки ТЕКУЩЕЙ реплики, уже загруженные
    вызывающим сценарием (`core.app.scenarios.prep_chat`); домен `preparation` не знает о
    хранилище вложений, только принимает готовые байты и прокидывает их в порт LLM.

    history[i]["content"] (Э3-3) может уже нести текст распознанных картинок ПРОШЛЫХ реплик
    (`analysis.title`/`.text`, обёрнутый `wrap_untrusted`) — эта функция сама вложений не
    читает, склейка происходит на роутере (`api.routers.preparation.mappers.prep_chat_llm_history`),
    домен здесь просто конкатенирует `content` как обычный текст реплики."""
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    context = await gather_prep_context(record.vacancy_id or "", stage, account_id=account_id)
    system = await _build_prep_chat_system(
        record,
        stage,
        profile,
        focus_topics,
        prep_questions,
        context.render(),
        pack_content,
        account_id=account_id,
    )
    history_text = "\n".join(
        f"{('Владелец' if h['role'] == 'user' else 'Коуч')}: {h['content']}" for h in history[-12:]
    )
    user = _build_prep_chat_user(record, message, history_text)

    raw = await ports.llm().complete(
        "prep", system=system, user=user, temperature=0.4, images=images
    )
    return _parse_chat_answer(raw)


# ---- sobes.tech контекст-шпаргалка ----

# Чего ждать / не ждать на формате - короткий канон для зачина оверлея (не путать форматы).
_SOBES_FORMAT_EXPECT: dict[str, str] = {
    "screening": (
        "HR-скрининг: мотивация, вилка, формат, лёгкая проверка опыта. "
        "Глубокой технички и live coding обычно нет."
    ),
    "tech": (
        "Техничка по стеку вакансии + прикладной кейс. "
        "Может быть теория и рассказ об опыте; live coding - только если HR явно сказал."
    ),
    "theory": (
        "Теория и рассказ об опыте: «как работает X», метрики, модели, рабочий кейс. "
        "Live coding обычно нет; system design - только если HR явно намекнул."
    ),
    "system_design": (
        "System design: один большой кейс на проектирование под стек вакансии "
        "(требования, узкие места, отказы, мониторинг). Live coding и чистая теория - не фокус."
    ),
    "live_coding": (
        "Live coding: код вживую, алгоритмы и/или практический кусок под стек. "
        "Длинный system design обычно нет."
    ),
    "business_case": (
        "Бизнес-кейс: задача → решение → данные → метрика → риск → impact. "
        "Чистый algo-live-coding обычно нет."
    ),
    "final": (
        "Финал с тимлидом/head of: ownership, команда, конфликт, куда расти. "
        "Глубокий live coding обычно нет; могут задеть прикладной кейс."
    ),
    "hr_final": ("HR-финал: деньги, условия, формат, сроки. Технических задач нет."),
    "other": (
        "Формат заранее смешанный: готовься к вопросам по стеку и опыту; "
        "уточняй по словам HR, если они есть во входе."
    ),
}


def fit_sobes_overlay_text(text: str, limit: int = SOBES_OVERLAY_MAX_CHARS) -> str:
    """Ужать готовый контекст оверлея до жёсткого потолка (по границе абзаца/строки)."""
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    for sep in ("\n\n", "\n", ". "):
        idx = cut.rfind(sep)
        if idx <= limit * 2 // 3:
            continue
        if sep == ". ":
            return cut[: idx + 1].rstrip()
        return cut[:idx].rstrip()
    return cut.rstrip()


def _build_sobes_user(
    record: VacancyRecord,
    stage: str,
    prep_questions: list[PrepQuestion],
    *,
    topics: list[str] | None = None,
    hr_stage_notes: str = "",
    weak_topics: str = "",
    strong_answers: str = "",
) -> str:
    """Узкий вход для синтеза оверлея: без чата и без простыней ответов подготовки."""
    title = record.title or "?"
    company = record.company or "?"
    stage_label = STAGE_LABELS.get(stage, stage)
    stage_expect = _SOBES_FORMAT_EXPECT.get(stage, _SOBES_FORMAT_EXPECT["other"])
    # Текст вакансии нужен модели для тем/роли; в выход оверлея целиком не попадёт.
    text = truncate_vacancy_text(record.vacancy_text or "", limit=3500)

    topics_block = ""
    if topics:
        topics_block = "## Темы подготовки (уже собраны)\n\n" + "\n".join(
            f"- {t}" for t in topics[:16]
        )

    q_block = ""
    if prep_questions:
        # Только формулировки вопросов - ответы в оверлей не тащим (раздувают и шумят).
        lines = [f"- {q.text.strip()}" for q in prep_questions[:12] if q.text.strip()]
        if lines:
            q_block = "## Уже отрабатывали в подготовке (только темы вопросов)\n\n" + "\n".join(
                lines
            )

    extras: list[str] = []
    if hr_stage_notes.strip():
        extras.append(f"## Слова HR про этот этап\n\n{hr_stage_notes.strip()}")
    if weak_topics.strip():
        extras.append(f"## Слабые зоны (не повторить)\n\n{weak_topics.strip()[:800]}")
    if strong_answers.strip():
        extras.append(f"## Козыри\n\n{strong_answers.strip()[:600]}")
    extras_block = "\n\n".join(extras)

    return f"""## Вакансия

Компания: {company}
Позиция: {title}
Этап (ключ): {stage}
Этап (лейбл): {stage_label}
Ожидание по формату: {stage_expect}

### Текст вакансии (для ориентации по темам и роли - НЕ копируй целиком в ответ)

{text}

{topics_block}

{q_block}

{extras_block}

Собери контекст для оверлея sobes.tech под ЭТОТ этап.
Жёсткий потолок ответа: {SOBES_OVERLAY_MAX_CHARS} символов.
"""


async def build_sobes_context(
    record: VacancyRecord,
    stage: str,
    prep_questions: list[PrepQuestion],
    chat_history: list[dict[str, str]] | None = None,
    *,
    account_id: int,
    topics: list[str] | None = None,
) -> str:
    """Компактный контекст для оверлея sobes.tech (≤ SOBES_OVERLAY_MAX_CHARS).

    `chat_history` оставлен в сигнатуре для совместимости роутера, в промпт больше не кладётся:
    туда часто попадают огромные внешние переписки и раздувают шум.
    """
    del chat_history  # явно не используем
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    context = await gather_prep_context(record.vacancy_id or "", stage, account_id=account_id)
    user = _build_sobes_user(
        record,
        stage,
        prep_questions,
        topics=topics,
        hr_stage_notes=context.next_stage,
        weak_topics=context.weak_topics,
        strong_answers=context.strong_answers,
    )
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    system = _load_prompt_file(_SOBES_OVERLAY_PROMPT).replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data)
    )
    # L-13: потолок держит LlmFeature "prep" (6144). Литерал max_tokens=2500 тут резал ответ
    # вместе с reasoning-токенами (reasoning_effort="medium") — оверлей приходил пустым.
    raw = await ports.llm().complete(
        "prep",
        system=system,
        user=user,
        temperature=0.35,
    )
    fitted = fit_sobes_overlay_text(raw)
    if len(raw.strip()) > SOBES_OVERLAY_MAX_CHARS:
        logger.info(
            "sobes-context: ответ ужат %d → %d символов",
            len(raw.strip()),
            len(fitted),
        )
    return fitted


__all__ = [
    "SOBES_OVERLAY_MAX_CHARS",
    "generate_prep_questions",
    "generate_prep_questions_events",
    "answer_prep_chat",
    "build_sobes_context",
    "fit_sobes_overlay_text",
    "checklist_for_stage",
    "framework_for_stage",
    "CATEGORY_LABELS",
    "STAGE_LABELS",
]
