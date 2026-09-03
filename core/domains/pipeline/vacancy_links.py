"""Извлечение ссылок и vacancy_id из текста HR-переписки."""

from __future__ import annotations

import re

_HH_VACANCY_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)?hh\.ru/vacancy/(\d+)(?:\?[^\s]*)?",
    re.IGNORECASE,
)

# Хабр Карьера: career.habr.com/vacancies/{id}. Канон vacancy_id — `habr_{id}` (префикс, как
# `gm_` у getmatch), чтобы один numeric на разных площадках не схлопывался в одну вакансию.
_HABR_VACANCY_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)?career\.habr\.com/vacancies/(\d+)",
    re.IGNORECASE,
)

# Вакансии на карьерных порталах / внутренних job-сайтах (не hh)
_JOB_URL_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)

_SKIP_URL_HOSTS = (
    "t.me",
    "telegram.",
    "zoom.us",
    "meet.google",
    "teams.microsoft",
    "jazz.sberbank",
    "calendar.google",
    "mail.google",
    "linkedin.com/in",
    "github.com",
    "gitlab.com",
)


def extract_vacancy_ids(text: str) -> list[str]:
    """Все vacancy_id из hh.ru- и career.habr.com-ссылок, без дублей, в порядке появления.

    hh — чистый numeric (как раньше); Хабр — каноничный `habr_{numeric}` (префикс, как `gm_`),
    чтобы numeric разных площадок не совпадал.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _HH_VACANCY_RE.finditer(text):
        vid = match.group(1)
        if vid not in seen:
            seen.add(vid)
            result.append(vid)
    for match in _HABR_VACANCY_RE.finditer(text):
        vid = f"habr_{match.group(1)}"
        if vid not in seen:
            seen.add(vid)
            result.append(vid)
    return result


def _is_job_listing_url(url: str) -> bool:
    lower = url.lower().rstrip(".,;)")
    if not lower.startswith("http"):
        return False
    for skip in _SKIP_URL_HOSTS:
        if skip in lower:
            return False
    # hh обрабатывается отдельно
    if "hh.ru/vacancy/" in lower:
        return False
    job_hints = (
        "/vacancy",
        "/vacancies/",
        "/job/",
        "/jobs/",
        "/career",
        "/careers",
        "/position",
        "/opening",
        "job. ",
        "jobs.",
        "career.",
        "talent.",
        "huntflow",
        "potok.io",
        "friendwork",
    )
    return any(h in lower for h in job_hints)


def extract_job_urls(text: str) -> list[str]:
    """Все URL вакансий (hh и внешние job/career), без дублей."""
    seen: set[str] = set()
    result: list[str] = []

    for match in _HH_VACANCY_RE.finditer(text):
        url = match.group(0)
        if not url.lower().startswith("http"):
            url = "https://" + url.lstrip("/")
        if url not in seen:
            seen.add(url)
            result.append(url)

    for match in _JOB_URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;)>]")
        if url in seen:
            continue
        if _is_job_listing_url(url):
            seen.add(url)
            result.append(url)

    return result


def extract_primary_vacancy_id(text: str, llm_url: str = "") -> str:
    """Первый vacancy_id из текста или из URL, который вернула LLM."""
    ids = extract_vacancy_ids(text)
    if ids:
        return ids[0]
    if llm_url:
        ids = extract_vacancy_ids(llm_url)
        if ids:
            return ids[0]
    return ""


def listing_url_for_vacancy_id(vacancy_id: str) -> str:
    """URL карточки вакансии по каноничному vacancy_id (hh numeric / `habr_{n}` / `gm_{n}`)."""
    vid = (vacancy_id or "").strip()
    if vid.startswith("habr_"):
        return f"https://career.habr.com/vacancies/{vid[5:]}"
    if vid.startswith("gm_"):
        return f"https://getmatch.ru/vacancies/{vid[3:]}"
    return f"https://hh.ru/vacancy/{vid}"


def extract_primary_job_url(text: str, llm_url: str = "") -> str:
    """Первая ссылка на вакансию: hh.ru или внешний job/career URL."""
    urls = extract_job_urls(text)
    if urls:
        return urls[0]
    if llm_url:
        llm = llm_url.strip()
        if llm and (_HH_VACANCY_RE.search(llm) or _is_job_listing_url(llm)):
            return llm if llm.startswith("http") else f"https://{llm.lstrip('/')}"
    vid = extract_primary_vacancy_id(text, llm_url)
    if vid:
        return listing_url_for_vacancy_id(vid)
    return ""


def extract_primary_vacancy_url(text: str, llm_url: str = "") -> str:
    """Алиас: первая ссылка на вакансию (hh или внешняя)."""
    return extract_primary_job_url(text, llm_url)
