"""Домен career: портфолио, лента, долгая память, режим/трек поиска, дружба.

`timeline` слушает шину (stage/offer/debrief/search_mode/search_track →
`career_timeline`). `portfolio` — черновики элементов из резюме/разборов/офферов
(`api/routers/career/portfolio.py`). `facts` — долгая память из разборов → prep/chat
(`api/routers/career/facts.py`). `search_state` — режим поиска (SearchMode) + журнал
переходов (`GET/PATCH /api/career/search-mode`). `track_state` — набор треков поиска
(основная / вторая работа, `GET/PATCH /api/career/track`). `friendships_repo` — коды
дружбы и связи друзей (`api/routers/career/friendships.py`).
"""

from __future__ import annotations

from core.domains.career.facts import (
    extract_facts_from_debrief_analysis,
    load_facts_context_block,
    record_facts_from_debrief,
    render_facts_block,
)
from core.domains.career.friendships_repo import (
    add_friend,
    are_friends,
    ensure_all_system_admin_friendships,
    ensure_all_system_admin_friendships_throttled,
    ensure_system_admin_friendships,
    get_friend_profile,
    get_or_create_friendship_code,
    list_friends,
    remove_friend,
    resolve_code,
)
from core.domains.career.models import (
    CareerFact,
    FriendEntry,
    FriendProfile,
    FriendshipCode,
    PortfolioItem,
    TimelineEvent,
)
from core.domains.career.portfolio import (
    draft_portfolio_from_debrief,
    draft_portfolio_from_offer,
    draft_portfolio_from_resume,
)
from core.domains.career.search_state import (
    SearchMode,
    SearchModeState,
    SearchStateEntry,
    get_current_state,
    set_search_mode,
)
from core.domains.career.timeline import (
    append_timeline_event,
    record_domain_event,
    timeline_from_stage_changed,
)
from core.domains.career.track_state import (
    TrackState,
    TrackStateEntry,
    get_current_tracks,
    set_second_job_enabled,
    set_tracks,
)

__all__ = [
    "CareerFact",
    "FriendEntry",
    "FriendProfile",
    "FriendshipCode",
    "PortfolioItem",
    "SearchMode",
    "SearchModeState",
    "SearchStateEntry",
    "TimelineEvent",
    "TrackState",
    "TrackStateEntry",
    "add_friend",
    "append_timeline_event",
    "are_friends",
    "draft_portfolio_from_debrief",
    "draft_portfolio_from_offer",
    "draft_portfolio_from_resume",
    "ensure_all_system_admin_friendships",
    "ensure_all_system_admin_friendships_throttled",
    "ensure_system_admin_friendships",
    "extract_facts_from_debrief_analysis",
    "get_current_state",
    "get_current_tracks",
    "get_friend_profile",
    "get_or_create_friendship_code",
    "list_friends",
    "load_facts_context_block",
    "record_domain_event",
    "record_facts_from_debrief",
    "remove_friend",
    "render_facts_block",
    "resolve_code",
    "set_search_mode",
    "set_second_job_enabled",
    "set_tracks",
    "timeline_from_stage_changed",
]
