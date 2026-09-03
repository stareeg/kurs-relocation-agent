"""События домена profile: что публикует и на что подписан (шина — A-11).

Снимок навыков (`skill_suggest.py`) пересобирается в фоне
по двум триггерам — `VacancyScored` копит счётчик «+N вакансий выборки», `ResumeUpdated`
проверяет, сдвинулся ли skills-отпечаток резюме. Оба уважают нижнюю границу между пересборками
и никогда не звонят на `GET`; сама проверка условий и single-flight — в `skill_suggest.py`,
здесь только провод от события к ней.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import ResumeUpdated, SearchTrackChanged, VacancyScored

PUBLISHES: tuple[type, ...] = (ResumeUpdated,)


async def on_vacancy_scored(evt: VacancyScored) -> None:
    """Новая/переоценённая вакансия — счётчик к порогу автопересборки снимка навыков."""
    if not evt.account_id:
        return
    from core.domains.profile.skill_suggest import maybe_auto_refresh_for_new_vacancies

    await maybe_auto_refresh_for_new_vacancies(account_id=evt.account_id)


async def on_resume_updated(evt: ResumeUpdated) -> None:
    """Резюме сохранено — пересобрать снимок навыков, только если сдвинулся skills-отпечаток
    (Решение 2): телефон/образование/языки его не двигают. Международный снимок — по хэшу
    всего резюме (язык/город/about как раз двигают его).
    """
    if not evt.account_id:
        return
    from core.domains.profile.intl_experience import maybe_refresh_snapshot
    from core.domains.profile.skill_suggest import maybe_auto_refresh_for_resume_change

    await maybe_auto_refresh_for_resume_change(account_id=evt.account_id)
    await maybe_refresh_snapshot(account_id=evt.account_id)


async def on_search_track_changed(evt: SearchTrackChanged) -> None:
    """Включили второй трек — снимок международного опыта нужен даже при рынке «Только РФ»."""
    if not evt.account_id or "second_job" not in evt.tracks:
        return
    from core.domains.profile.intl_experience import maybe_refresh_snapshot

    await maybe_refresh_snapshot(account_id=evt.account_id, force=True)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (VacancyScored, on_vacancy_scored),
    (ResumeUpdated, on_resume_updated),
    (SearchTrackChanged, on_search_track_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)


def publish_resume_updated(*, source: str = "", account_id: int | None = None) -> None:
    """Резюме сохранено: от него зависят скоринг, профиль поиска и ATS-fit.

    `source` — какая ручка сохранила (`resume_save`, `resume_patch`, …): по нему в витрине
    видно, откуда приехало изменение. `account_id=None` — bootstrap-путь (файл, ни одного
    аккаунта ещё нет) — подписчики (`on_resume_updated`) событие с `account_id=0` пропускают.
    """
    ports.events().publish(ResumeUpdated(source=source, account_id=account_id or 0))


__all__ = [
    "PUBLISHES",
    "ResumeUpdated",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "VacancyScored",
    "on_resume_updated",
    "on_search_track_changed",
    "on_vacancy_scored",
    "publish_resume_updated",
]
