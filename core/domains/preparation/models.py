"""Схемы подготовки к собесу и разбора собеса.

LLM-вход/выход (вопросы prep, разбор debrief) и таксономия для рендеров бота. Персист prep-
сессий — `core.domains.preparation.prep` (questions/responses как jsonb-словари), здесь — типизированный
вопрос (`PrepQuestion`), который сериализуем в jsonb при записи, и результат разбора
(`DebriefAnalysis`), который кладём в `enrichment.interview_debrief`.

`VacancyRecord` (запись вакансии + оценка) — здесь же: её ждёт Q&A-asker
(`core.domains.preparation.asker`). `ScoreResult` не дублируем — источник истины
`core.domains.opportunities.models`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.opportunities.models import ScoreResult
from core.kernel.schemas.funnel import FunnelStatus


def _now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "PrepCategory",
    "PrepStage",
    "PrepStatus",
    "STAGE_LABELS",
    "CATEGORY_LABELS",
    "PrepQuestion",
    "ChatAnswer",
    "NextStepsSignal",
    "SIGNAL_LABELS",
    "SIGNAL_LABELS_WEB",
    "WeakAnswer",
    "HonestNote",
    "InterviewFormat",
    "INTERVIEW_FORMAT_LABELS",
    "TranscriptSpeaker",
    "TranscriptTurn",
    "DebriefAnalysis",
    "StageOutcomeKind",
    "STAGE_OUTCOME_LABELS",
    # ---- Уровень владения темой: карта компетенций разбора собеса ----
    "MockMastery",
    "MockCompetency",
    # ---- Оценка ответа на реально заданный вопрос собеса (по расшифровке) ----
    "QuestionMastery",
    # ---- HR-этапы собеседований ----
    "InterviewStageType",
    "InterviewStageStatus",
    "SalaryMatch",
    "STAGE_TYPE_LABELS",
    "STAGE_TO_FUNNEL_STATUS",
    "InterviewStageIn",
    "InterviewData",
    "InterviewRecord",
    # ---- запись вакансии + оценка (Q&A-asker) ----
    "ScoreResult",
    "VacancyRecord",
]

# ---- prep ----

PrepCategory = Literal["technical", "behavioral", "case", "questions_to_ask"]
# Этапы воронки (screening/tech/final/hr_final) + явные форматы технички (theory/live_coding/
# system_design/business_case/other). Вкладка «Технички» работает с форматами; «Разбор»
# и бот по-прежнему оперируют этапами воронки. Ключ — общий keyspace `prep_sessions`.
# `final` (и синонимичные по факту soft_skills/manager) маппится в FunnelStatus.FINAL —
# см. STAGE_TO_FUNNEL_STATUS. `hr_final` воронку не двигает (обсуждение оффера/условий,
# живёт внутри стадии «Оффер»), остаётся только форматом подготовки.
PrepStage = Literal[
    "screening",
    "tech",
    "theory",
    "system_design",
    "live_coding",
    "business_case",
    "final",
    "hr_final",
    "other",
]
PrepStatus = Literal["generated", "in_progress", "finished", "skipped"]

STAGE_LABELS: dict[str, str] = {
    "screening": "HR-скрининг",
    "tech": "Техничка",
    "theory": "Теория",
    "system_design": "System design",
    "live_coding": "Live coding",
    "business_case": "Бизнес-кейс",
    "final": "Финал",
    "hr_final": "HR-финал",
    "other": "Другое",
}

CATEGORY_LABELS: dict[str, str] = {
    "technical": "🧪 Технический",
    "behavioral": "🧠 Поведенческий",
    "case": "🧩 Кейс / system design",
    "questions_to_ask": "❓ Спросить компанию",
}


class PrepQuestion(BaseModel):
    category: PrepCategory
    text: str = Field(min_length=3, max_length=2000)
    hint: str = ""
    # Готовый ответ на вопрос (markdown: текст/код/схема) — для режима «Подготовка» во вкладке
    # «Технички». Генерируется вместе с вопросом в одном LLM-вызове. Пусто — для старых записей
    # и для бота (ему вопросы нужны без ответов). Фронт рендерит через MarkdownView (код, mermaid,
    # формулы, **жирный**).
    answer: str = ""
    # Жизненный цикл вопроса после разбора собеса: "asked" — реально выпал на этапе,
    # "unused" — подготовлен, но не пригодился, None — этап ещё не пройден/не разобран (матчинг
    # `core.interview.question_match` проставляет это поле best-effort после сохранения дебрифа).
    outcome: Literal["asked", "unused"] | None = None
    # RD-22b: как кандидат ответил на этот вопрос — матчинг question_match переносит уровень из
    # `debrief.question_mastery` в сматченный вопрос; None — ответа нет (фронт ставит «Под вопросом»).
    mastery: Literal["confident", "medium", "weak"] | None = None
    # PREP-4: ярлык пачки («Kafka/Flink»), только у вопросов, добавленных чатом («Ещё пачку по X»,
    # PREP-3) — фронт группирует подряд идущие карточки с одинаковым topic под заголовком. Первичная
    # генерация (`generate_prep_questions`) оставляет None — плоский список, как раньше.
    topic: str | None = None


class ChatAnswer(BaseModel):
    """Ответ LLM в чат подготовки: обычная реплика ИЛИ новая пачка вопросов-карточек.

    "kind"="questions" — владелец попросил ещё вопросов/пачку по теме; "text" тогда короткое
    подтверждение (НЕ дублирует вопросы текстом), "questions" — новая пачка той же схемы, что
    генерация подготовки, персистится в `prep_sessions` вместо оседания как текст в чате.
    "kind"="chat" — обычный ответ, "questions" пуст. Битый JSON от LLM деградирует в "chat" с
    сырым текстом (не теряем ответ) — см. `core.domains.preparation.interview.prep._parse_chat_answer`.
    """

    kind: Literal["chat", "questions"] = "chat"
    text: str = ""
    topic: str | None = None
    questions: list[PrepQuestion] = Field(default_factory=list)


# ---- уровень владения темой: карта компетенций разбора собеса ----

# Насколько уверенно кандидат владеет темой - по ответу на собесе (debrief).
MockMastery = Literal["confident", "medium", "weak"]


class MockCompetency(BaseModel):
    """Пункт карты компетенций: тема + уровень владения + на чём основано."""

    topic: str = Field(min_length=1, max_length=200)
    level: MockMastery = "medium"
    evidence: str = ""


class QuestionMastery(BaseModel):
    """Оценка ответа на реально заданный вопрос собеса (по расшифровке).

    Покрывает только те вопросы из `questions_asked`, где в транскрипте ЕСТЬ ответ кандидата.
    Вопрос без ответа (задали — ответ не прозвучал) в список не попадает: фронт показывает
    честную плашку «Под вопросом» вместо выдуманной оценки.
    """

    question: str = Field(min_length=1, max_length=1000)
    level: MockMastery = "medium"


# ---- debrief ----

NextStepsSignal = Literal[
    "offer_likely",
    "next_stage_likely",
    "ambiguous",
    "rejection_likely",
    "unknown",
]

SIGNAL_LABELS: dict[str, str] = {
    "offer_likely": "🟢 Похоже на оффер",
    "next_stage_likely": "🟢 Двигаемся дальше",
    "ambiguous": "🟡 Непонятно",
    "rejection_likely": "🔴 Похоже на отказ",
    "unknown": "⚪ Сигнал не считывается",
}

#: То же без эмодзи — веб рисует сигнал своим цветом, а промпт следующего разбора цитирует
#: подпись предыдущего этапа (эмодзи там лишний шум).
SIGNAL_LABELS_WEB: dict[str, str] = {
    "offer_likely": "Похоже на оффер",
    "next_stage_likely": "Двигаемся дальше",
    "ambiguous": "Сигнал неоднозначный",
    "rejection_likely": "Похоже на отказ",
    "unknown": "Сигнал не считывается",
}


class WeakAnswer(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    what_went_wrong: str = Field(min_length=1, max_length=2000)
    how_to_improve: str = Field(min_length=1, max_length=2000)
    # JS-14: эталонный ответ (2-4 предложения) - что стоило сказать вместо/в дополнение.
    reference_answer: str = ""


class HonestNote(BaseModel):
    """Вопрос, который сам кандидат явно пометил как нечестный/непроверенный ответ (подсказка,
    чужой код, не отвечал сам) - "честный счёт": не считается провальным ответом в
    агрегатной оценке (overall_impression/weak_answers), помечается отдельно."""

    question: str = Field(min_length=1, max_length=2000)
    note: str = Field(min_length=1, max_length=500)


# Автоопределённый формат интервью из транскрипта - разные критерии оценки: для
# hr_screening/final значима структура истории и коммуникация, не корректность кода/архитектуры.
InterviewFormat = Literal["technical", "system_design", "final", "hr_screening", "other"]

INTERVIEW_FORMAT_LABELS: dict[str, str] = {
    "technical": "Техническое",
    "system_design": "System design",
    "final": "Финал",
    "hr_screening": "HR-скрининг",
    "other": "Другое",
}


TranscriptSpeaker = Literal["interviewer", "candidate"]


class TranscriptTurn(BaseModel):
    """Одна реплика транскрипта после LLM-сегментации: монологи сжаты до сути,
    тайм-коды/технический мусор диктофона убраны, хронология сохранена."""

    speaker: TranscriptSpeaker
    text: str = Field(min_length=1, max_length=600)
    # UX3-DBR: время реплики (ISO 8601), если LLM смогла извлечь его из исходного транскрипта
    # (тайм-коды диктофона, метки чата Zoom/Teams). None — фронт подставляет время начала разбора.
    ts: str | None = None


class DebriefAnalysis(BaseModel):
    """Результат анализа транскрипта одного собеса."""

    questions_asked: list[str] = Field(default_factory=list)
    weak_answers: list[WeakAnswer] = Field(default_factory=list)
    strong_answers: list[str] = Field(default_factory=list)
    topics_to_study: list[str] = Field(default_factory=list)
    next_steps_signal: NextStepsSignal = "unknown"
    overall_impression: int = Field(ge=1, le=10, default=5)
    summary: str = ""
    analyzed_at: datetime = Field(default_factory=_now_utc)
    # JS-14: карта компетенций по темам транскрипта (не плоский topics_to_study).
    competency_map: list[MockCompetency] = Field(default_factory=list)
    # JS-14: автоопределённый формат интервью → в промпте применены его критерии оценки.
    interview_format: InterviewFormat = "other"
    # JS-14: "честный счёт" - вопросы с явным маркером нечестного ответа, исключённые из оценки.
    honest_notes: list[HonestNote] = Field(default_factory=list)
    # DBR-3: транскрипт, сегментированный LLM на реплики вопрос/ответ — компактный чат вместо
    # одного текстового блоба. Пусто для старых записей (миграции) или если LLM не сегментировала.
    transcript_turns: list[TranscriptTurn] = Field(default_factory=list)
    # Оценка ответа по каждому реально заданному вопросу (конфидент/средне/слабо); вопросы без
    # ответа в расшифровке в списке отсутствуют — фронт ставит «Под вопросом».
    question_mastery: list[QuestionMastery] = Field(default_factory=list)


# ---- stage outcome: структурный исход этапа от рекрутера, без транскрипта ----

# Исход пройденного этапа: двинулись дальше / отказ / ждём ответа. Кейс «отказ без комментариев» —
# валидная запись (частый случай), это данные для калибровки, а не пустота.
StageOutcomeKind = Literal["passed", "rejected", "waiting"]

STAGE_OUTCOME_LABELS: dict[str, str] = {
    "passed": "Прошёл дальше",
    "rejected": "Отказ",
    "waiting": "Ждём ответа",
}


# ---- HR-этапы собеседований ----

InterviewStageType = Literal[
    "hr_screening",
    "live_coding",
    "system_design",
    "theory",
    "soft_skills",
    "manager",
    "business_case",
    "final",
]

InterviewStageStatus = Literal[
    "scheduled",
    "completed",
    "cancelled",
    "rescheduled",
    "failed",
]

SalaryMatch = Literal["yes", "no", "unclear"]

STAGE_TYPE_LABELS: dict[str, str] = {
    "hr_screening": "HR-скрининг",
    "live_coding": "Live coding",
    "system_design": "System design",
    "theory": "Теория",
    "soft_skills": "Soft skills",
    "manager": "Менеджер",
    "business_case": "Бизнес-кейс",
    "final": "Финал",
}

STAGE_TO_FUNNEL_STATUS: dict[str, str] = {
    "hr_screening": FunnelStatus.SCREENING,
    "live_coding": FunnelStatus.TECH,
    "system_design": FunnelStatus.TECH,
    "theory": FunnelStatus.TECH,
    "soft_skills": FunnelStatus.FINAL,
    "manager": FunnelStatus.FINAL,
    "business_case": FunnelStatus.TECH,
    "final": FunnelStatus.FINAL,
}


class InterviewStageIn(BaseModel):
    """Этап из LLM-парсера HR-сообщения (до привязки vacancy_id)."""

    stage_type: InterviewStageType = "hr_screening"
    scheduled_at: datetime | None = None
    format: Literal["online", "offline", "unknown"] = "unknown"
    status: InterviewStageStatus = "scheduled"
    notes: str = ""


class InterviewData(BaseModel):
    """Распознанные данные о собеседовании из HR-сообщения (порт bot.schemas.interview)."""

    company: str
    position: str
    interview_dt: datetime | None = None
    format: Literal["online", "offline", "unknown"] = "unknown"
    interviewer_name: str = ""
    contact: str = ""
    raw_text: str
    parsed_at: datetime = Field(default_factory=_now_utc)

    # После создания события в Calendar.
    calendar_event_id: str = ""
    calendar_event_url: str = ""

    # Служебные.
    db_id: int | None = None
    telegram_msg_id: int | None = None


class InterviewRecord(InterviewData):
    db_id: int = 0


# ---- запись вакансии + оценка (вход Q&A-asker) ----


class VacancyRecord(BaseModel):
    id: int | None = None
    vacancy_text: str
    url: str | None = None
    vacancy_id: str | None = None
    title: str | None = None
    company: str | None = None
    salary_text: str | None = None
    area: str | None = None
    work_schedule: str | None = None
    total_responses: int | None = Field(default=None, ge=0)
    letter_required: bool | None = None
    published_at: str | None = None
    cover_letter_text: str | None = None
    employer_id: str | None = None
    source: str | None = None
    is_archived: bool = False
    status: str | None = None
    scored_at: datetime = Field(default_factory=_now_utc)
    score: ScoreResult
