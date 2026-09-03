"""Человекочитаемые исходы автоотклика и классификация сбоев.

Раннер расширения шлёт машинный `outcome` (`no_button`, `timeout`, …). Здесь — только
словари и чистые хелперы без I/O: сценарий `report_attempt` решает, куда двигать очередь,
а UI показывает `failure_reason` на строке «Ручной разбор».
"""

from __future__ import annotations

# Исходы DOM-флоу, при которых реальный автоотклик не ушёл — вакансию пора отдать человеку.
# `dry_run` тут тоже: если площадка уже в боевом режиме, а content-script всё равно вернул
# dry_run — это сбой контракта, а не намеренный тест.
FAILURE_OUTCOMES: frozenset[str] = frozenset(
    {
        "no_button",
        "not_ready",
        "timeout",
        "error",
        "unsupported",
        "dry_run",
    }
)

# Уже откликнулись на площадке — синхронизируем воронку, не тащим в ручной разбор.
SYNC_APPLIED_OUTCOMES: frozenset[str] = frozenset({"already_applied", "applied"})

# Подмножество FAILURE_OUTCOMES со смыслом «не смогли ПОДТВЕРДИТЬ», а не «точно не отправили».
# Клик по «Откликнуться» уже произошёл, и площадка могла принять отклик — просто маркеры успеха
# не появились в отведённое окно (`apply_confirm_timeout_ms`). Прод 2026-08-31, job 867: hh.ru
# показал поверх страницы свою модалку («в каком городе ищете работу»), маркеры «Резюме
# доставлено» из-за неё не проявились за 8 с — раннер отрапортовал `error`, хотя отклик УШЁЛ
# (`application_stages` записал `Отклик` от `api_funnel` за секунду до этого репорта).
# Такие исходы обязаны сверяться с фактической стадией воронки прежде, чем ехать в ручной разбор.
UNCONFIRMED_OUTCOMES: frozenset[str] = frozenset({"timeout", "error"})

OUTCOME_RU: dict[str, str] = {
    "no_button": "На странице не нашлась кнопка «Откликнуться»",
    "not_ready": "Страница вакансии не успела загрузиться",
    "timeout": "Площадка слишком долго отвечала",
    "error": "Сбой при отправке отклика",
    "unsupported": "Автоотклик для этой площадки пока не поддерживается",
    "already_applied": "Отклик на эту вакансию уже был отправлен раньше",
    "dry_run": "Отклик не ушёл — расширение отработало в режиме проверки",
    "captcha": "Площадка показала капчу или блокировку",
    "resume_hidden": "Резюме скрыто от работодателей",
    "platform_limit": "Достигнут дневной лимит откликов на площадке",
    "anketa": "Нужно заполнить анкету работодателя",
    "needs_confirmation": "Ждёт вашего подтверждения перед отправкой",
}


def failure_reason_ru(outcome: str | None) -> str:
    """Короткое пояснение для UI; неизвестный исход — общая формулировка."""
    if not outcome:
        return "Не удалось отправить автоотклик"
    return OUTCOME_RU.get(outcome, "Не удалось отправить автоотклик")


def is_failure_outcome(outcome: str | None) -> bool:
    return bool(outcome) and outcome in FAILURE_OUTCOMES


def is_unconfirmed_outcome(outcome: str | None) -> bool:
    """Исход «не смогли подтвердить» — отклик мог уйти, см. `UNCONFIRMED_OUTCOMES`."""
    return bool(outcome) and outcome in UNCONFIRMED_OUTCOMES


__all__ = [
    "FAILURE_OUTCOMES",
    "OUTCOME_RU",
    "SYNC_APPLIED_OUTCOMES",
    "UNCONFIRMED_OUTCOMES",
    "failure_reason_ru",
    "is_failure_outcome",
    "is_unconfirmed_outcome",
]
