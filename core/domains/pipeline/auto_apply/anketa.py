"""Ответы на анкету работодателя при отклике (Фаза 3.2, auto_apply_roadmap_2026_08_17.md).

hh.ru — единственная площадка с этой механикой (живая разведка DOM,
`plans/hh_integration/anketa_example_bankssoft.md`). Вопросы парсит расширение
(`extension/src/content/hh-apply-flow.ts`) и присылает уже структурированными (текст + тип +
варианты, `AnketaQuestion`). Для `single_choice`/`multi_choice` модель выбирает текст
варианта(ов) ДОСЛОВНО из присланного списка — числовые ID вариантов на стороне hh.ru
непрозрачны и не нужны модели; сопоставление текста на реальный `id` происходит здесь по
точному совпадению label (см. `_resolve_choice_answer`), а итоговая привязка к DOM-`value`
(атрибуту инпута) — уже в расширении при заполнении формы, там же, где живут актуальные
`options` конкретной вакансии.

Один LLM-вызов на всю анкету (не по вопросу) — дешевле и даёт модели видеть все вопросы сразу
для согласованных ответов между собой (например, опыт с БД и опыт с ORM не должны противоречить
друг другу). Анти-slop: `lint_spoken_text` на каждый `text`-ответ + один ремонтный вызов при
нарушениях (тот же паттерн, что `screening/questions.py::_generate_hr_questions` — там же
прецедент tier=advanced/reasoning_effort=medium для черновиков ответов на вопросы).
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from core.domains.opportunities.models import AnketaAnswer, AnketaQuestion
from core.domains.opportunities.prompt import load_candidate_identity, load_resume
from core.domains.preparation.models import VacancyRecord
from core.domains.preparation.vacancy_context import truncate_vacancy_text
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.text import SPOTLIGHT_RULE, wrap_untrusted
from core.kernel.text.style_lint import StyleViolation, lint_spoken_text
from core.platform.observability import event

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Ты отвечаешь на анкету работодателя при отклике на вакансию за конкретного
кандидата ({identity}). Анкета — часть формы отклика на hh.ru: работодатель попросит ответить
на несколько вопросов, чтобы решить, стоит ли открывать резюме.

## Резюме кандидата

{resume}

## Вакансия

Компания: {company}
Позиция: {title}

### Текст вакансии

{vacancy_text}

{spotlight_rule}

## Вопросы анкеты

{questions_block}

## Как отвечать

1. Отвечай ТОЛЬКО на основе резюме и текста вакансии. Не выдумывай факты, которых там нет —
   если резюме не даёт прямого ответа, бери максимально консервативную честную формулировку
   (например «базовое понимание», не «глубокая экспертиза»), не угадывай цифры и названия.
2. Вопросы с типом «один вариант» или «несколько вариантов» — верни ТЕКСТ варианта(ов)
   ДОСЛОВНО из присланного списка (для нескольких — через "; "), не перефразируй и не
   придумывай новый вариант, которого нет в списке.
3. Вопросы с типом «свободный текст» — 1-3 коротких предложения, конкретика (проект,
   технология, цифра из резюме), не пересказ всего резюме.
4. Вопрос про желаемый уровень дохода/зарплаты — отвечай ПРЯМО конкретной цифрой или
   диапазоном из резюме, не уклоняйся и не пиши «обсудим на собеседовании».
5. Telegram-контакт (ник) добавляй в ответ ТОЛЬКО если вопрос буквально просит контакт для
   связи (например «как с вами связаться», «оставьте телефон или мессенджер») — в остальных
   ответах его не упоминай, это будет выглядеть как баг, не как забота.

## Стиль (свободный текст) — маркеры ИИ-ответа, которые работодатель узнаёт с одного взгляда

- Никаких длинных тире, минимум двоеточий (не используй двоеточие как связку перед
  перечислением).
- Никакого канцелярита («осуществлял», «реализовывал», «позволяет», «способствует») и
  корпоративных клише («высокая мотивация», «глубокая экспертиза», «стремлюсь внести вклад»).
- Без англицизмов-бизнес-жаргона (например "Time-to-Market" — используй "срок вывода",
  "срок подготовки" и т.п.). Точные названия технологий (Kafka, Docker, FastAPI и т.п.) —
  оставляй как есть, это не англицизм-слоп, а термин.
- Простые прямые предложения, активные глаголы, без вводных слов-паразитов.

Верни ТОЛЬКО структурированный ответ, без пояснений до или после."""


class _AnketaAnswerDraft(BaseModel):
    question_id: str
    answer: str = ""


class _AnketaAnswerBatch(BaseModel):
    answers: list[_AnketaAnswerDraft] = Field(default_factory=list)


def _question_block(question: AnketaQuestion) -> str:
    wrapped = wrap_untrusted(question.text, source="hh_anketa_question")
    if question.type == "text":
        return f"### Вопрос {question.id} (свободный текст)\n{wrapped}"
    kind = "один вариант" if question.type == "single_choice" else "один или несколько вариантов"
    options = "\n".join(f"- {opt.label}" for opt in question.options)
    return f"### Вопрос {question.id} ({kind} из списка ниже)\n{wrapped}\nВарианты:\n{options}"


async def _build_system_prompt(
    questions: list[AnketaQuestion], record: VacancyRecord, *, account_id: int
) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    return _SYSTEM_PROMPT.format(
        identity=load_candidate_identity(data=resume_data),
        resume=load_resume(data=resume_data),
        company=record.company or "не указана",
        title=record.title or "не указана",
        vacancy_text=truncate_vacancy_text(record.vacancy_text or "", limit=6000),
        spotlight_rule=SPOTLIGHT_RULE,
        questions_block="\n\n".join(_question_block(q) for q in questions),
    )


def _build_repair_prompt(
    drafts: list[_AnketaAnswerDraft], flagged: list[tuple[str, list[StyleViolation]]]
) -> str:
    flagged_ids = {qid for qid, _ in flagged}
    current = "\n".join(f"{d.question_id}: {d.answer}" for d in drafts)
    lines = [f"Вопрос {qid} — {v.detail}" for qid, violations in flagged for v in violations]
    return f"""## Текущие ответы

{current}

## Нарушения стиля — исправить каждое

{chr(10).join(f"{i}. {line}" for i, line in enumerate(lines, start=1))}

Перепиши ответы ЦЕЛИКОМ (все question_id из текущих ответов). Меняй ТОЛЬКО текст ответов на
вопросы {sorted(flagged_ids)}, остальные оставь дословно как есть. Факты не меняй, только стиль."""


async def _call_answers(system: str, user: str) -> list[_AnketaAnswerDraft]:
    result = await ports.llm().structured(
        "anketa_answer",
        system=system,
        user=user,
        schema=_AnketaAnswerBatch,
        temperature=0.3,
        max_retries=1,
    )
    if not isinstance(result, _AnketaAnswerBatch) or not result.answers:
        raise LlmError("LLM вернул пустой список ответов анкеты")
    return result.answers


def _resolve_choice_answer(question: AnketaQuestion, raw_answer: str) -> str:
    """Сопоставить свободный текст модели с реальными label вариантов вопроса.

    Возвращает человекочитаемое значение (label(ы) через "; "), НЕ числовой DOM-`value` —
    привязка к `value` происходит в расширении при заполнении формы по этим же `options`.
    Несовпавший фрагмент отбрасывается с предупреждением в лог (лучше неполный, но валидный
    ответ, чем выдуманный вариант, которого нет на форме).
    """
    labels_by_norm = {opt.label.strip().lower(): opt.label for opt in question.options}
    picked: list[str] = []
    for fragment in re.split(r"[;,\n]", raw_answer):
        norm = fragment.strip().lower()
        if norm in labels_by_norm and labels_by_norm[norm] not in picked:
            picked.append(labels_by_norm[norm])
    if not picked:
        logger.warning(
            "anketa: ответ модели не совпал ни с одним вариантом вопроса %s: %r",
            question.id,
            raw_answer,
        )
        return ""
    if question.type == "single_choice":
        picked = picked[:1]
    return "; ".join(picked)


async def generate_anketa_answers(
    questions: list[AnketaQuestion], record: VacancyRecord, *, account_id: int
) -> list[AnketaAnswer]:
    """Резюме + вакансия + вопросы анкеты → черновик ответов (для очереди подтверждения,
    Фаза 3.3 — владелец видит и правит ДО реальной отправки, эта функция не финальна).

    S-critical (2026-08-26): резюме — аккаунта запроса (см. `core.domains.pipeline.cover_letter`,
    тот же класс бага). Особо критично здесь — ответы анкеты уходят в реальную форму hh.ru.
    """
    if not questions:
        return []

    system = await _build_system_prompt(questions, record, account_id=account_id)
    user = "Ответь на все вопросы анкеты по инструкции выше."
    drafts = await _call_answers(system, user)
    questions_by_id = {q.id: q for q in questions}

    text_drafts = [
        d for d in drafts if getattr(questions_by_id.get(d.question_id), "type", None) == "text"
    ]
    flagged = [
        (d.question_id, violations)
        for d in text_drafts
        if (violations := lint_spoken_text(d.answer))
    ]

    if flagged:
        total_before = sum(len(v) for _, v in flagged)
        logger.info(
            "anketa_answer: %d нарушений устного стиля (%d вопросов из %d), запускаю ремонт",
            total_before,
            len(flagged),
            len(drafts),
        )
        try:
            drafts = await _call_answers(system, _build_repair_prompt(drafts, flagged))
        except LlmError as exc:
            event(
                logger,
                "LLM",
                "anketa_answer: ремонт не удался, отдаю черновик как есть: %s",
                exc,
                vacancy_id=record.vacancy_id,
                issues_before=total_before,
                repaired=False,
                level=logging.WARNING,
            )

    event(
        logger,
        "LLM",
        "anketa_answer: собрано %d ответов на анкету",
        len(drafts),
        vacancy_id=record.vacancy_id,
        questions=len(questions),
        repaired=bool(flagged),
    )

    answers: list[AnketaAnswer] = []
    for draft in drafts:
        question = questions_by_id.get(draft.question_id)
        if question is None:
            continue
        value = (
            _resolve_choice_answer(question, draft.answer)
            if question.type != "text"
            else draft.answer.strip()
        )
        answers.append(AnketaAnswer(question_id=draft.question_id, value=value))
    return answers


__all__ = ["generate_anketa_answers"]
