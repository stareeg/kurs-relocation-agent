"""Обогащение ленты «Карьеры» названием/компанией вакансии — на чтении, не на записи (Э10,
plans/career_redesign_2026_08_26.md, Этап 2).

`core.domains.career.timeline` кладёт в `TimelineEvent.title` сырой `vacancy_id` — мапперы там
чистые и без I/O (см. `core/domains/career/README.md`), а вакансии — чужой для `career` домен.
Резолвинг живёт здесь, в кросс-доменном сценарии (`app` уже это делает для остального экрана —
`career_snapshot.py`), и возвращает голые данные, а не транспортную схему: `TimelineEventView`
(с `company`/`vacancy_title`/`href`) — в `api/schemas`, `app` не имеет права её знать (`app` ниже
`api` по слоям, `docs/ARCHITECTURE.md`). Собирает `TimelineEventView` роутер.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.domains.career.models import TimelineEvent


class VacancyRef(BaseModel):
    """Название/компания одной вакансии для одной строки ленты.

    Пусто (`company`/`title` — "") — вакансия не резолвится (архив, вакансия с площадки без
    карточки в `jobs`, ручная веха без `vacancy_id`); фолбэк на сырой id остаётся на роутере.
    """

    company: str = ""
    title: str = ""


def _vacancy_ids(events: list[TimelineEvent]) -> list[str]:
    ids: set[str] = set()
    for ev in events:
        vid = str(ev.payload.get("vacancy_id") or "").strip()
        if vid:
            ids.add(vid)
    return list(ids)


async def load_vacancy_refs(
    events: list[TimelineEvent], *, account_id: int
) -> dict[str, VacancyRef]:
    """Карта `vacancy_id` → `VacancyRef` для всех событий пачки, один запрос вместо N.

    Best-effort: вакансия не нашлась (архивирована и удалена, или id с площадки без карточки в
    `jobs` — `gm_.../tg_web_...` без импорта) — просто не попадает в карту, роутер уже умеет
    показать сырой id как фолбэк.
    """
    from core.domains.opportunities.jobs import get_jobs_by_vacancy_ids

    ids = _vacancy_ids(events)
    if not ids:
        return {}
    jobs = await get_jobs_by_vacancy_ids(ids, account_id=account_id)
    return {
        vid: VacancyRef(company=job.company or "", title=job.title or "")
        for vid, job in jobs.items()
        if job.company or job.title
    }


__all__ = ["VacancyRef", "load_vacancy_refs"]
