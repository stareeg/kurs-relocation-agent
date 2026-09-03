"""Роутеры API, сгруппированные по доменам.

Физически: ``api/routers/<domain>/*.py``. Публичный импорт сохранён:
``from api.routers import score`` / ``interview_stages`` — через реэкспорт ниже.
``mount_routers`` — единая точка регистрации в ``api.main`` (URL не меняются).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from api.routers.assistant import attachments, chat, conversations, notes
from api.routers.career import facts as career_facts
from api.routers.career import friendships as career_friendships
from api.routers.career import portfolio as career_portfolio
from api.routers.career import search_mode
from api.routers.career import snapshot as career_snapshot
from api.routers.career import timeline as career_timeline
from api.routers.career import track as career_track
from api.routers.market import analytics, narrative, resume_stats
from api.routers.meta import admin, auth, events, logs, tasks, telegram, views
from api.routers.meta import meta as meta_router
from api.routers.multiplayer import rooms as multiplayer_rooms
from api.routers.multiplayer import ws as multiplayer_ws
from api.routers.offers import offers
from api.routers.opportunities import (
    companies,
    discovery,
    parser_config,
    score,
    score_revision,
    skipped,
    vacancies,
)
from api.routers.pipeline import auto_apply, cover_letter, funnel, hr_threads, negotiations
from api.routers.preparation import (
    debrief,
    interview_stages,
    prep,
    screening,
)
from api.routers.profile import avatar, resume, settings

# Совместимость с ``from api.routers import <module>`` (main, тесты).
meta = meta_router

__all__ = [
    "analytics",
    "attachments",
    "auth",
    "auto_apply",
    "avatar",
    "career_friendships",
    "career_portfolio",
    "career_facts",
    "career_snapshot",
    "career_timeline",
    "chat",
    "companies",
    "conversations",
    "cover_letter",
    "debrief",
    "discovery",
    "events",
    "funnel",
    "hr_threads",
    "interview_stages",
    "logs",
    "meta",
    "mount_routers",
    "multiplayer_rooms",
    "multiplayer_ws",
    "narrative",
    "negotiations",
    "notes",
    "offers",
    "parser_config",
    "prep",
    "resume",
    "resume_stats",
    "score",
    "score_revision",
    "screening",
    "search_mode",
    "career_track",
    "settings",
    "skipped",
    "tasks",
    "telegram",
    "vacancies",
    "views",
]


def mount_routers(app: FastAPI, *, require_account: Any) -> None:
    """Подключить все роутеры. Порядок как до R-34; пути URL без изменений.

    Публичные: ``auth`` (и ``/health`` в main). Остальные — за ``require_account`` (Этап 2):
    гейт 401/bootstrap тот же, что был у ``require_auth``, но конкретному роутеру видна
    личность (``AccountContext | None``) — он подключает её через свой собственный
    ``Depends(require_account)`` там, где она нужна (FastAPI кэширует зависимость на запрос).
    """
    auth_deps = [Depends(require_account)]
    app.include_router(auth.router)
    app.include_router(admin.router, dependencies=auth_deps)
    app.include_router(auto_apply.router, dependencies=auth_deps)
    app.include_router(attachments.router, dependencies=auth_deps)
    app.include_router(avatar.router, dependencies=auth_deps)
    app.include_router(chat.router, dependencies=auth_deps)
    app.include_router(views.router, dependencies=auth_deps)
    app.include_router(score.router, dependencies=auth_deps)
    app.include_router(vacancies.router, dependencies=auth_deps)
    app.include_router(funnel.router, dependencies=auth_deps)
    app.include_router(negotiations.router, dependencies=auth_deps)
    app.include_router(offers.router, dependencies=auth_deps)
    app.include_router(resume.router, dependencies=auth_deps)
    app.include_router(resume_stats.router, dependencies=auth_deps)
    app.include_router(screening.router, dependencies=auth_deps)
    app.include_router(hr_threads.router, dependencies=auth_deps)
    app.include_router(conversations.router, dependencies=auth_deps)
    app.include_router(notes.router, dependencies=auth_deps)
    app.include_router(prep.router, dependencies=auth_deps)
    app.include_router(cover_letter.router, dependencies=auth_deps)
    app.include_router(debrief.router, dependencies=auth_deps)
    app.include_router(interview_stages.router, dependencies=auth_deps)
    app.include_router(score_revision.router, dependencies=auth_deps)
    app.include_router(skipped.router, dependencies=auth_deps)
    app.include_router(analytics.router, dependencies=auth_deps)
    app.include_router(analytics.market_router, dependencies=auth_deps)
    app.include_router(narrative.router, dependencies=auth_deps)
    app.include_router(meta.router, dependencies=auth_deps)
    app.include_router(companies.router, dependencies=auth_deps)
    app.include_router(discovery.router, dependencies=auth_deps)
    app.include_router(parser_config.router, dependencies=auth_deps)
    app.include_router(settings.router, dependencies=auth_deps)
    app.include_router(telegram.router, dependencies=auth_deps)
    app.include_router(logs.router, dependencies=auth_deps)
    app.include_router(tasks.router, dependencies=auth_deps)
    app.include_router(events.router, dependencies=auth_deps)
    app.include_router(search_mode.router, dependencies=auth_deps)
    app.include_router(career_track.router, dependencies=auth_deps)
    app.include_router(career_snapshot.router, dependencies=auth_deps)
    app.include_router(career_timeline.router, dependencies=auth_deps)
    app.include_router(career_facts.router, dependencies=auth_deps)
    app.include_router(career_friendships.router, dependencies=auth_deps)
    app.include_router(career_portfolio.router, dependencies=auth_deps)
    app.include_router(multiplayer_rooms.router, dependencies=auth_deps)
    # WS сам аутентифицирует (cookie/query) — без HTTP Depends(require_account).
    app.include_router(multiplayer_ws.router)
