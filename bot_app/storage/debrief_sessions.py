"""Краткоживущий in-memory кэш последнего debrief в чате — для callback-кнопок (S10).

Порт `bot.storage.debrief_sessions`: хранит результат разбора, чтобы кнопки «темы»/«полный
разбор» отдавали данные без повторного LLM-вызова.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DebriefState:
    vacancy_id: str
    analysis: dict
    interview_id: int | None = None


_states: dict[int, DebriefState] = {}


def remember(chat_id: int, state: DebriefState) -> None:
    _states[chat_id] = state


def get(chat_id: int) -> DebriefState | None:
    return _states.get(chat_id)


def clear(chat_id: int) -> None:
    _states.pop(chat_id, None)
