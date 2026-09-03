"""Транспортные схемы API: screening."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Раздел «Скрининги»: вопросы под вакансию, которые кандидат задаёт HR ---

# --- Раздел «Скрининги»: канонический пакет (защита + нападение, FR3-49/50) ---


class ScreeningQuestionsRequest(BaseModel):
    """Сгенерировать пакет скрининга под вакансию (LLM). Контекст передаём напрямую (как prep)."""

    vacancy_id: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=300)
    company: str = Field(default="", max_length=300)
    vacancy_text: str = Field(default="", max_length=40_000)


class ScreeningMoreQuestionsRequest(BaseModel):
    """Догенерировать ещё пачку вопросов в уже собранный пакет (без пересборки легенды)."""

    kind: Literal["hr", "ask"]
    title: str = Field(default="", max_length=300)
    company: str = Field(default="", max_length=300)
    vacancy_text: str = Field(default="", max_length=40_000)
    count: int = Field(default=6, ge=1, le=12)


class ScreeningDeleteQuestionRequest(BaseModel):
    """Удалить один вопрос из собранного пакета (hr — от HR, иначе — вопрос к HR)."""

    kind: Literal["hr", "ask"]
    question: str = Field(min_length=1, max_length=500)


class ScreeningPitchEditRequest(BaseModel):
    """Ручная правка «Рассказа об опыте» (закреплённое сообщение в чате Скринингов, п.2)."""

    oral_pitch: str = Field(min_length=1, max_length=20_000)


# Типизированные модели для OpenAPI (зеркало core.screening.questions/pitch/pack). Репозиторий
# хранит jsonb как list[dict], публичный контракт типизирован — фронт берёт типы из schema.d.ts.
class ScreeningQuestion(BaseModel):
    """Один вопрос, который кандидат задаёт HR: что хотим понять + что вероятно услышим."""

    question: str
    probe: str = Field(default="", description="Что хотим понять этим вопросом")
    expect: str = Field(default="", description="Что вероятно услышим и как это трактовать")


class QuestionGroup(BaseModel):
    """Группа вопросов кандидат→HR, придуманная под конкретную вакансию."""

    title: str
    hook: str = Field(
        default="", description="Фраза вакансии (или дыра в ней), из-за которой группа появилась"
    )
    questions: list[ScreeningQuestion] = Field(default_factory=list)


class HrQuestion(BaseModel):
    """Вероятный вопрос HR к кандидату: требование вакансии, за которым он стоит, что этим
    проверяют + черновик ответа."""

    question: str
    requirement: str = ""
    intent: str = ""
    draft_answer: str


class PitchBlock(BaseModel):
    """Один блок устного рассказа: подпись + произносимые строки."""

    label: str = ""
    lines: list[str] = Field(default_factory=list)


class SavedScreeningQuestions(BaseModel):
    """Сохранённый пакет скрининга под вакансию (кэш последней генерации в БД)."""

    vacancy_id: str
    groups: list[QuestionGroup] = Field(default_factory=list)
    hr_questions: list[HrQuestion] = Field(default_factory=list)
    why_company: str = ""
    oral_pitch: str = ""
    pitch_blocks: list[PitchBlock] = Field(default_factory=list)
    jd_brief: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime | None = None


__all__ = [
    "ScreeningQuestionsRequest",
    "ScreeningMoreQuestionsRequest",
    "ScreeningDeleteQuestionRequest",
    "ScreeningPitchEditRequest",
    "ScreeningQuestion",
    "QuestionGroup",
    "HrQuestion",
    "PitchBlock",
    "SavedScreeningQuestions",
]
