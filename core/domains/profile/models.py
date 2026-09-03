"""Доменные модели профиля: ResumeData + CandidateProfile (без HTTP/SQL)."""

from __future__ import annotations

from core.domains.profile.international import InternationalReadiness
from core.domains.profile.model import (
    Contacts,
    Course,
    DesiredPosition,
    Education,
    Experience,
    Language,
    Personal,
    ResumeData,
    ResumeDataPatch,
    SearchCriteria,
    apply_city_derived_countries,
    to_markdown,
)
from core.domains.profile.profile import (
    GRADE_SCALE,
    CandidateProfile,
    CandidateProfileOverlay,
    SearchProfile,
    apply_candidate_overlay,
    clear_candidate_profile_cache,
    clear_search_profile_cache,
    derive_candidate_profile,
    derive_search_profile,
    load_candidate_profile,
    load_candidate_profile_enriched,
    load_search_profile,
)

__all__ = [
    "GRADE_SCALE",
    "CandidateProfile",
    "CandidateProfileOverlay",
    "Contacts",
    "Course",
    "DesiredPosition",
    "Education",
    "Experience",
    "InternationalReadiness",
    "Language",
    "Personal",
    "ResumeData",
    "ResumeDataPatch",
    "SearchCriteria",
    "SearchProfile",
    "apply_candidate_overlay",
    "apply_city_derived_countries",
    "clear_candidate_profile_cache",
    "clear_search_profile_cache",
    "derive_candidate_profile",
    "derive_search_profile",
    "load_candidate_profile",
    "load_candidate_profile_enriched",
    "load_search_profile",
    "to_markdown",
]
