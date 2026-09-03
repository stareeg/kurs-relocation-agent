"""Доступ к данным профиля: файловый стор резюме + PG (score history, hh/getmatch/habr/tg stats)."""

from __future__ import annotations

from core.domains.profile.resume_score import (
    ResumeScoreSnapshot,
    load_score_at,
    load_score_history,
    save_score_snapshot,
)
from core.domains.profile.resume_stats import (
    GETMATCH_PROFILE_RESUME_ID,
    ResumeStatSnapshot,
    ResumeView,
    list_resume_stats,
    list_resume_views,
    save_resume_stat,
    save_resume_views,
)
from core.domains.profile.structured_store import (
    load_resume_into_runtime,
    read_resume_data_for_account,
    read_resume_data_for_default_account,
    read_resume_data_from_file,
    render_resume_markdown_for_account,
    save_resume_data,
)

__all__ = [
    "GETMATCH_PROFILE_RESUME_ID",
    "ResumeScoreSnapshot",
    "ResumeStatSnapshot",
    "ResumeView",
    "list_resume_stats",
    "list_resume_views",
    "load_resume_into_runtime",
    "load_score_at",
    "load_score_history",
    "read_resume_data_for_account",
    "read_resume_data_for_default_account",
    "read_resume_data_from_file",
    "render_resume_markdown_for_account",
    "save_resume_data",
    "save_resume_stat",
    "save_resume_views",
    "save_score_snapshot",
]
