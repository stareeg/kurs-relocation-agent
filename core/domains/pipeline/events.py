"""События домена pipeline: что публикует и на что подписан (шина — A-11).

`ApplicationStageChanged` публикует opportunities: единственная точка записи стадии —
`add_stage`, и pipeline тоже ходит в неё, а не пишет воронку сам.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import ApplicationStageChanged, HrMessageReceived
from core.kernel.ids import VacancyId
from core.kernel.schemas.funnel import FunnelStatus, is_engaged_status

PUBLISHES: tuple[type, ...] = (HrMessageReceived,)


async def on_application_stage_changed(evt: ApplicationStageChanged) -> None:
    """Отказ ⇒ HR-диалог вакансии уходит в архив Чатов; возврат в активную стадию ⇒ обратно.

    Раньше каждый вызывающий `opportunities.add_stage` сам был обязан не забыть дёрнуть
    архив/разархив тредов (`service.py::set_job_stage`/`record_apply`, `negotiations.py` — три
    копии одной и той же логики) — и как минимум один путь (`preparation.interview.
    debrief_resolution` — авто-отказ по красному дебрифу) этого не делал вовсе: вакансия уезжала
    в «Отказ», а её HR-чат оставался «active» (баг, воспроизведённый на проде — job 251,
    debrief_auto_reject, 2026-08-13). Эффект теперь живёт у владельца `hr_threads` и срабатывает
    на КАЖДОЙ смене стадии, откуда бы она ни пришла — тот же приём, что уже применён ниже
    `preparation.events.on_application_stage_changed` для отметки пройденного HR-скрининга.
    """
    if not evt.vacancy_id or not evt.account_id:
        return
    if evt.stage == FunnelStatus.REJECTED.value:
        from core.domains.pipeline.hr_threads import archive_threads_for_vacancy

        await archive_threads_for_vacancy(evt.vacancy_id, account_id=evt.account_id)
    elif is_engaged_status(evt.stage):
        from core.domains.pipeline.hr_threads import unarchive_threads_for_vacancy

        await unarchive_threads_for_vacancy(evt.vacancy_id, account_id=evt.account_id)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (ApplicationStageChanged, on_application_stage_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)


def publish_hr_message_received(
    *,
    vacancy_id: str = "",
    thread_id: str = "",
    intent: str = "",
    funnel_status: str = "",
    channel: str = "",
    account_id: int,
) -> None:
    """Пачка HR-переписки разобрана и применена к воронке."""
    ports.events().publish(
        HrMessageReceived(
            vacancy_id=VacancyId(vacancy_id),
            thread_id=thread_id,
            intent=intent,
            funnel_status=funnel_status,
            channel=channel,
            account_id=account_id,
        )
    )


__all__ = [
    "HrMessageReceived",
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "on_application_stage_changed",
    "publish_hr_message_received",
]
